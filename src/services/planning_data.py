"""Bounded, revision-aware caches for planning inputs and selected-project reads."""

from contextlib import closing

import streamlit as st

from src.database.connection import get_db
from src.repositories.project_repo import ProjectRepository
from src.repositories.milestone_repo import MilestoneRepository
from src.repositories.tag_repo import TagRepository
from src.repositories.organization_repo import OrganizationRepository
from src.repositories.schema_repo import SchemaRepository
from src.repositories.resource_pool_repo import ResourcePoolRepository
from src.services.organization_service import OrganizationService
from src.services.portfolio_service import PortfolioService


def ensure_planning_indexes(db_path=None):
    """Idempotent for existing bind-mounted databases as well as fresh schemas."""
    with closing(get_db(db_path)) as conn:
        with conn:
            conn.execute('CREATE INDEX IF NOT EXISTS idx_planning_task_project ON project_task(project_id,start_date,id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_planning_dependency_task ON task_dependencies(task_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_planning_dependency_predecessor ON task_dependencies(predecessor_task_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_planning_dependency_project ON task_dependencies(predecessor_project_id)')
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='planning_summary_cache'").fetchone():
                from src.services.planning_summary_cache import install_summary_cache
                install_summary_cache(conn)


@st.cache_data(ttl=60, max_entries=8, show_spinner=False)
def load_planning_catalog(db_path, revision, property_ids=()):
    ensure_planning_indexes(db_path)
    projects = ProjectRepository(db_path).get_planning_catalog(property_ids)
    params = SchemaRepository(db_path).get_all_parameters()
    org = OrganizationRepository(db_path)
    # Organization labels are calculated once per revision, not once per rerun.
    frame = (PortfolioService.flatten_dynamic_attributes(projects, params[params.param_id.isin(property_ids)])
             if property_ids else projects.copy())
    frame = OrganizationService.enrich_projects_with_organization(frame, org.get_all_functions(), org.get_all_employees())
    tags = TagRepository(db_path).get_all_project_tags().to_dict('records')
    return projects, frame, params, tags


@st.cache_data(ttl=60, max_entries=8, show_spinner=False)
def load_planning_steps(db_path, revision, project_ids):
    repo = MilestoneRepository(db_path)
    steps = repo.get_milestones_for_projects(list(project_ids))
    dependencies = repo.get_dependencies_for_projects(list(project_ids))
    task_ids = steps.id.tolist() if not steps.empty else []
    return (steps, dependencies, TagRepository(db_path).get_task_tags_by_task_ids(task_ids),
            ResourcePoolRepository(db_path).get_task_assignments_map(task_ids))


@st.cache_data(ttl=60, max_entries=8, show_spinner=False)
def load_planning_project_metadata(db_path, revision, project_ids):
    return (TagRepository(db_path).get_project_tags_by_project_ids(list(project_ids)),
            ResourcePoolRepository(db_path).get_project_assignments_map(list(project_ids)))


@st.cache_data(ttl=60, max_entries=4, show_spinner=False)
def load_planning_bounds(db_path, revision):
    return MilestoneRepository(db_path).get_all_project_date_bounds()


@st.cache_data(ttl=60, max_entries=16, show_spinner=False)
def load_dependency_choices(db_path, revision, project_id):
    steps = MilestoneRepository(db_path).get_milestones_for_projects([project_id])
    return steps[['id', 'task_name', 'start_date', 'end_date']].to_dict('records') if not steps.empty else []


@st.cache_data(ttl=60, max_entries=8, show_spinner=False, hash_funcs={tuple: repr})
def load_project_summaries(db_path, revision, project_ids):
    """Small summary records, including exact warnings for unloaded tasks."""
    import json
    with closing(get_db(db_path)) as conn:
        conn.execute('BEGIN IMMEDIATE')  # Do not publish a summary over a concurrent task edit.
        cached = {row[0]: row for row in conn.execute('SELECT * FROM planning_summary_cache WHERE project_id IN (SELECT value FROM json_each(?))', (json.dumps(project_ids),))}
        project_ids = tuple(pid for pid in project_ids if pid not in cached)
        if not project_ids:
            return [dict(zip(('id','name','start','end','taskCount','progress','hasViolations'), row)) for row in cached.values()]
        rows = conn.execute('''WITH scope AS (SELECT value id FROM json_each(?)), bounds AS (
            SELECT project_id,MIN(start_date) start,MAX(end_date) end,COUNT(*) task_count,
                   AVG(progress_pct) progress FROM project_task
            WHERE project_id IN (SELECT id FROM scope UNION SELECT d.predecessor_project_id
                FROM task_dependencies d JOIN project_task s ON s.id=d.task_id
                WHERE s.project_id IN (SELECT id FROM scope) AND d.predecessor_task_id IS NULL)
            GROUP BY project_id
        ), violations AS (
            SELECT s.project_id,COUNT(*) violations FROM task_dependencies d
            JOIN project_task s ON s.id=d.task_id
            LEFT JOIN project_task p ON p.id=d.predecessor_task_id
            LEFT JOIN bounds b ON b.project_id=d.predecessor_project_id
            WHERE s.project_id IN (SELECT id FROM scope) AND
              julianday(CASE WHEN UPPER(d.link_type) IN ('FF','SF') THEN s.end_date ELSE s.start_date END)
              < julianday(CASE WHEN d.predecessor_task_id IS NOT NULL THEN
                  CASE WHEN UPPER(d.link_type) IN ('SS','SF') THEN p.start_date ELSE p.end_date END
                ELSE CASE WHEN UPPER(d.link_type) IN ('SS','SF') THEN b.start ELSE b.end END END)
                + COALESCE(d.lag_days,0)
            GROUP BY s.project_id
        ) SELECT p.id,p.name,b.start,b.end,COALESCE(b.task_count,0),COALESCE(b.progress,0),
                 COALESCE(v.violations,0)>0
          FROM project p LEFT JOIN bounds b ON b.project_id=p.id
          LEFT JOIN violations v ON v.project_id=p.id
          WHERE p.id IN (SELECT id FROM scope) ORDER BY p.id''',
          (json.dumps(project_ids),)).fetchall()
        with conn:
            conn.executemany('INSERT OR REPLACE INTO planning_summary_cache VALUES(?,?,?,?,?,?,?)', rows)
    return [dict(zip(('id','name','start','end','taskCount','progress','hasViolations'), row)) for row in sorted(list(cached.values()) + rows)]


def affected_task_projects(db_path, task_id):
    """The edited project plus successors that reference the task or its summary."""
    with closing(get_db(db_path)) as conn:
        row = conn.execute('SELECT project_id FROM project_task WHERE id=?', (task_id,)).fetchone()
        if not row:
            return set(), set()
        pid = row[0]
        projects = {pid} | {r[0] for r in conn.execute('''SELECT DISTINCT t.project_id FROM task_dependencies d
            JOIN project_task t ON t.id=d.task_id WHERE d.predecessor_task_id=? OR d.predecessor_project_id=?''', (task_id,pid))}
        pools = {r[0] for r in conn.execute('SELECT DISTINCT pool_id FROM resource_pool_assignment WHERE project_id=?', (pid,))}
    return projects, pools


def build_task_payload(db_path, project_ids, bounds, pool_details):
    """Hydrate only requested projects, with the same constraint/capacity semantics."""
    from src.repositories.portfolio_repo import portfolio_revision
    from src.services.milestone_service import MilestoneService
    steps, deps, tags, pools = load_planning_steps(db_path, portfolio_revision(db_path), tuple(sorted(project_ids)))
    if steps.empty:
        return []
    records = steps.to_dict('records')
    for dependency in deps:
        pid = dependency.get('predecessor_project_id')
        if pid and not dependency.get('predecessor_task_id') and str(pid) not in bounds:
            bounds[str(pid)] = MilestoneRepository(db_path).get_project_date_bounds(pid)
    evaluated, violations = MilestoneService.evaluate_constraints(records, deps, bounds)
    by_task = {}
    for dep in evaluated:
        by_task.setdefault(int(dep['task_id']), []).append(dep)
    names = {p['id']: p['name'] for p in load_project_summaries(db_path, portfolio_revision(db_path), tuple(sorted(project_ids)))}
    result = []
    for row in records:
        tid = int(row['id'])
        enriched = []
        for assignment in pools.get(tid, []):
            assignment = dict(assignment)
            detail = pool_details.get(assignment['pool_id'])
            if detail:
                start = assignment.get('start_date') or row['start_date']
                end = assignment.get('end_date') or row['end_date']
                assignment['pool_capacity'] = detail.total_capacity_fte
                assignment['is_overassigned'] = (float(assignment['fte']) > detail.total_capacity_fte + 1e-4
                    or any(str(start) <= d.date <= str(end) for d in detail.daily_overassignments))
            enriched.append(assignment)
        result.append({'id': str(tid), 'name': row['task_name'], 'start': row['start_date'], 'end': row['end_date'],
            'project_id': str(row['project_id']), 'project_name': names.get(row['project_id'], str(row['project_id'])),
            'progress': int(row.get('progress_pct',0)), 'phase': row.get('phase','General'),
            'description': row.get('description') or '', 'dependenciesList': by_task.get(tid,[]),
            'violations': violations.get(tid,[]), 'tags': tags.get(tid,[]), 'pools': enriched})
    return result

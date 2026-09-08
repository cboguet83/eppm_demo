"""Database Seeding Utility.

Populates the EPPM database with realistic projects, hierarchical milestone schedules,
and rich internal and external task dependencies.
"""

from contextlib import closing

import argparse
import datetime
import os
import random
import sys
import time
from typing import Any, Optional

# Ensure project root is in sys.path when running script directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.demo_catalog import DEMO_TYPES, sample_values
from src.database.property_store import effective_template
from src.repositories.project_repo import ProjectRepository
from src.models.constants import STATUS_LIST
from scripts.flush_database import flush_database
from src.database.connection import get_db
from src.database.backup import backup_before_seed
from src.database.schema_init import init_db
from src.database.seeder import seed_default_data_if_empty
from src.logging_config import get_logger

logger = get_logger(__name__)

# Sample Data Dictionaries for Realistic Generation
PROJECT_SUFFIXES: list[str] = [
    "Phase 1", "Phase 2", "Phase 3", "Mise à jour", "Etude", "Pilote"
]

TASK_TEMPLATES: list[tuple[str, str]] = [
    ("FAI", "Phase 1 - FAI"),
    ("APS", "Phase 2 - APS"),
    ("APD1", "Phase 3 - APD1"),
    ("APD2", "Phase 4 - APD2"),
    ("EXE", "Phase 5 - EXE"),
    ("CHA", "Phase 6 - CHA"),
    ("DEF", "Phase 7 - DEF"),
    ("N/A", "Phase 0 - N/A"),
]

# Default task durations (in days):
# FAI, APS, APD1: 12 months (365d)
# APD2, DEF: 18 months (548d)
# EXE: 6 months (182d)
# CHA: 24 months (730d)
TASK_DEFAULT_DURATIONS_DAYS: dict[str, int] = {
    "FAI": 365,
    "APS": 365,
    "APD1": 365,
    "APD2": 548,
    "EXE": 182,
    "CHA": 730,
    "DEF": 548,
}

MILESTONE_TEMPLATES: list[tuple[str, str]] = [
    ("AUT", "Autorisation 1"),
    ("VAL", "Validation"),
    ("QUAL", "Controle Qualité"),
    ("CER", "Certificat Conformité"),
]

PROJECT_STATUSES = STATUS_LIST

@backup_before_seed
def seed_database(
    num_projects: int = 1000,
    min_tasks_per_project: int = 0,
    max_tasks_per_project: int = 15,
    db_path: Optional[str] = None,
    clean_first: bool = True,
    random_seed: Optional[int] = 42,
) -> dict[str, int]:
    """Generates and seeds projects, tasks, and dependency links into SQLite.

    Args:
        num_projects: Total number of projects to generate. Default 1000.
        min_tasks_per_project: Minimum tasks per project (>=0). Default 0.
        max_tasks_per_project: Maximum tasks per project (<=50). Default 15.
        db_path: Optional SQLite database path.
        clean_first: If True, wipes existing records and runs seeder.py before generating projects. Default True.
        random_seed: Random seed for reproducible generation.

    Returns:
        dict[str, int]: Summary counts of generated objects.
    """
    if num_projects < 0 or min_tasks_per_project < 0 or max_tasks_per_project < min_tasks_per_project or max_tasks_per_project > 50:
        raise ValueError("Invalid project or task count")
    rng = random.Random(random_seed)
    start_time = time.time()
    logger.info("Initializing database and preparing seeding for %d projects...", num_projects)

    init_db(db_path)

    if clean_first:
        flush_database(db_path, flush_all=True)

    # Execute default data seeder (populates schema groups, parameters, organization hierarchy, functions, employees)
    seed_default_data_if_empty(db_path, include_projects=False)

    # Generate against the persisted catalog, preserving custom templates in append mode.
    projects_data = []
    project_ids = []
    base_start_date = datetime.date(2025, 6, 1)
    with closing(get_db(db_path)) as conn, conn:
        first_id = conn.execute("SELECT MAX(COALESCE((SELECT MAX(id) FROM project),0), COALESCE((SELECT seq FROM sqlite_sequence WHERE name='project'),0))+1").fetchone()[0]
        task_id_base = max(conn.execute("SELECT COALESCE(MAX(id),0) FROM project_task").fetchone()[0],
                            conn.execute("SELECT COALESCE((SELECT seq FROM sqlite_sequence WHERE name='project_task'),0)").fetchone()[0])
        persisted = dict(conn.execute("SELECT name,id FROM project_type ORDER BY id"))
        type_ids = [persisted[n] for n in DEMO_TYPES if n in persisted]
        type_ids += [tid for tid in persisted.values() if tid not in type_ids]
        labels = {v: k for k, v in persisted.items()}
        templates = {tid: effective_template(conn, tid) for tid in type_ids}
        options = {}
        for pid, value in conn.execute("SELECT param_id,option_value FROM schema_param_options ORDER BY display_order,id"):
            options.setdefault(pid, []).append(value)
        managers = [r[0] for r in conn.execute("SELECT function_id FROM function ORDER BY function_id")]
        for i in range(num_projects):
            p_id = first_id + i
            project_ids.append(p_id)
            type_id = type_ids[i % len(type_ids)]
            name = f"{labels[type_id]} — {rng.choice(PROJECT_SUFFIXES)} #{p_id}"
            status = rng.choice(PROJECT_STATUSES)
            planned = round(rng.uniform(50_000, 3_000_000), 2)
            actual = round(planned * rng.uniform(0, 1), 2)
            attrs = sample_values(conn, type_id, p_id, rng, template=templates[type_id], options=options)
            manager = rng.choice(managers) if managers else None
            projects_data.append((p_id, name, status, planned, actual, attrs, manager, type_id))
    # 2. Build Tasks / Milestones Payload
    # Structure: [(project_id, task_name, phase, start_date, end_date, progress_pct, description)]
    milestones_data: list[tuple[int, str, str, str, str, int, str]] = []
    project_task_indices: dict[int, list[int]] = {p_id: [] for p_id in project_ids}
    project_task_id_by_code: dict[int, dict[str, int]] = {p_id: {} for p_id in project_ids}
    global_task_counter = task_id_base

    # Store planned task dates for dependency validation
    task_date_map: dict[int, tuple[datetime.date, datetime.date, int]] = {}

    standard_tasks_type2 = [tmpl for tmpl in TASK_TEMPLATES if tmpl[0] != "N/A"]

    for p_idx, p_id in enumerate(project_ids):
        p_status = projects_data[p_idx][2]
        p_offset_days = rng.randint(0, 365)
        cur_date = base_start_date + datetime.timedelta(days=p_offset_days)

        if max_tasks_per_project == 0:
            continue

        # Schedule shape is independent of the project's property template.
        can_be_type_1 = (min_tasks_per_project <= 1 <= max_tasks_per_project)
        can_be_type_2 = (max_tasks_per_project >= 2) or (min_tasks_per_project == 0 and max_tasks_per_project >= 1)

        if can_be_type_1 and not can_be_type_2:
            is_type_1 = True
        elif can_be_type_2 and not can_be_type_1:
            is_type_1 = False
        else:
            is_type_1 = rng.random() < 0.20

        if is_type_1:
            # =================================================================
            # Single-phase schedule (3 months to 3 years).
            # =================================================================
            duration_days = rng.randint(90, 1095)
            task_start = cur_date
            task_end = task_start + datetime.timedelta(days=duration_days)

            if p_status == "Completed":
                prog_pct = 100
            elif p_status in ("Draft", "Draft"):
                prog_pct = 0
            else:
                prog_pct = rng.choice([0, 25, 50, 75, 100])

            global_task_counter += 1
            milestones_data.append((
                p_id,
                "N/A",
                "Phase 0 - N/A",
                task_start.isoformat(),
                task_end.isoformat(),
                prog_pct,
                "Phase unique N/A",
            ))
            project_task_indices[p_id].append(global_task_counter)
            project_task_id_by_code[p_id]["N/A"] = global_task_counter
            task_date_map[global_task_counter] = (task_start, task_end, p_id)

        else:
            # =================================================================
            # Multi-phase schedule (FAI, APS, APD1, APD2, EXE, CHA, DEF)
            # plus 0 to all milestone templates (AUT, VAL, QUAL, CER).
            # Never duplicated within a project.
            # =================================================================
            max_tasks_allowed = min(len(standard_tasks_type2), max_tasks_per_project)
            if max_tasks_per_project >= len(standard_tasks_type2):
                chosen_tasks = standard_tasks_type2
            else:
                chosen_tasks = standard_tasks_type2[:max_tasks_allowed]

            tasks_count = len(chosen_tasks)
            remaining_min = max(0, min_tasks_per_project - tasks_count)
            remaining_max = max(0, max_tasks_per_project - tasks_count)

            max_m = min(len(MILESTONE_TEMPLATES), remaining_max)
            min_m = min(max_m, remaining_min)

            if max_m >= min_m and max_m > 0:
                num_milestones = rng.randint(min_m, max_m)
            elif max_m > 0:
                num_milestones = max_m
            else:
                num_milestones = 0

            chosen_milestones = rng.sample(MILESTONE_TEMPLATES, k=num_milestones) if num_milestones > 0 else []

            # 1. Schedule Tasks sequentially with specific durations
            phase_end_dates: dict[str, datetime.date] = {}
            task_items: list[dict[str, Any]] = []

            for t_code, t_phase in chosen_tasks:
                duration_days = TASK_DEFAULT_DURATIONS_DAYS.get(t_code, 365)
                task_start = cur_date
                task_end = task_start + datetime.timedelta(days=duration_days)
                phase_end_dates[t_code] = task_end
                cur_date = task_end  # Next phase starts as previous ends

                task_items.append({
                    "code": t_code,
                    "name": t_code,
                    "phase": t_phase,
                    "start": task_start,
                    "end": task_end,
                    "is_milestone": False,
                })

            # 2. Schedule Milestones at relevant milestone anchor dates
            for m_code, m_name in chosen_milestones:
                if m_code == "AUT":
                    m_date = phase_end_dates.get("APS", phase_end_dates.get("APD1", cur_date))
                elif m_code == "VAL":
                    m_date = phase_end_dates.get("APD2", cur_date)
                elif m_code == "QUAL":
                    m_date = phase_end_dates.get("CHA", cur_date)
                elif m_code == "CER":
                    m_date = phase_end_dates.get("DEF", cur_date)
                else:
                    m_date = cur_date

                task_items.append({
                    "code": m_code,
                    "name": m_code,
                    "phase": m_name,
                    "start": m_date,
                    "end": m_date,
                    "is_milestone": True,
                })

            # Honor minimums above the standard catalog with unique work packages.
            package = 1
            while len(task_items) < min_tasks_per_project:
                end = cur_date + datetime.timedelta(days=30)
                task_items.append({"code": f"WP{package}", "name": f"Work package {package}",
                    "phase": "EXE", "start": cur_date, "end": end, "is_milestone": False})
                cur_date = end
                package += 1

            # Sort items chronologically by start date
            task_items.sort(key=lambda x: (x["start"], 0 if not x["is_milestone"] else 1))

            # Determine progress across the project lifecycle
            num_items = len(task_items)
            active_index = rng.randint(0, num_items - 1) if num_items > 0 else 0

            for idx, item in enumerate(task_items):
                global_task_counter += 1

                if p_status == "Completed":
                    prog_pct = 100
                elif p_status in ("Draft", "Draft"):
                    prog_pct = 0
                elif p_status == "In Progress":
                    if idx < active_index:
                        prog_pct = 100
                    elif idx == active_index:
                        prog_pct = 100 if item["is_milestone"] else rng.choice([25, 50, 75])
                    else:
                        prog_pct = 0
                else:
                    prog_pct = rng.choice([0, 0, 25, 50, 75, 100])

                desc = f"Livrable {item['name']} ({item['phase']})"

                milestones_data.append((
                    p_id,
                    item["name"],
                    item["phase"],
                    item["start"].isoformat(),
                    item["end"].isoformat(),
                    prog_pct,
                    desc,
                ))

                project_task_indices[p_id].append(global_task_counter)
                project_task_id_by_code[p_id][item["code"]] = global_task_counter
                task_date_map[global_task_counter] = (item["start"], item["end"], p_id)

    # 3. Build Dependencies Payload (Internal & External Links)
    # Structure: [(task_id, predecessor_task_id, predecessor_project_id, link_type, lag_days)]
    dependencies_data: list[tuple[int, Optional[int], Optional[str], str, int]] = []

    for p_idx, p_id in enumerate(project_ids):
        p_task_ids = project_task_indices[p_id]
        code_map = project_task_id_by_code[p_id]
        if not p_task_ids:
            continue

        # A. Internal Dependencies for Type 2 Sequential Pipeline
        ordered_phases = ["FAI", "APS", "APD1", "APD2", "EXE", "CHA", "DEF"]
        for i in range(len(ordered_phases) - 1):
            curr_code = ordered_phases[i + 1]
            prev_code = ordered_phases[i]
            if curr_code in code_map and prev_code in code_map:
                dependencies_data.append((
                    code_map[curr_code],
                    code_map[prev_code],
                    None,
                    "FS",
                    0,
                ))

        # Milestone dependencies
        if "AUT" in code_map and "APS" in code_map:
            dependencies_data.append((code_map["AUT"], code_map["APS"], None, "FS", 0))
        if "VAL" in code_map and "APD2" in code_map:
            dependencies_data.append((code_map["VAL"], code_map["APD2"], None, "FS", 0))
        if "QUAL" in code_map and "CHA" in code_map:
            dependencies_data.append((code_map["QUAL"], code_map["CHA"], None, "FS", 0))
        if "CER" in code_map and "DEF" in code_map:
            dependencies_data.append((code_map["CER"], code_map["DEF"], None, "FS", 0))

        # B. External Dependencies across Projects (for ~20% of projects)
        if p_idx > 0 and rng.random() < 0.22:
            first_task_id = p_task_ids[0]
            ext_p_idx = rng.randint(0, p_idx - 1)
            ext_p_id = project_ids[ext_p_idx]
            ext_p_tasks = project_task_indices[ext_p_id]

            if rng.random() < 0.40 or not ext_p_tasks:
                dependencies_data.append((
                    first_task_id,
                    None,
                    ext_p_id,
                    rng.choice(["FS", "SS"]),
                    rng.choice([0, 2, 5]),
                ))
            else:
                ext_pred_task_id = rng.choice(ext_p_tasks)
                dependencies_data.append((
                    first_task_id,
                    ext_pred_task_id,
                    ext_p_id,
                    rng.choice(["FS", "SS", "FF"]),
                    rng.choice([0, 1, 3]),
                ))

    # 4. Fast SQLite Transaction Execution
    with closing(get_db(db_path)) as conn, conn:

        cursor = conn.cursor()

        # Use the same validation and typed writer as interactive creation.
        for pid, name, status, planned, actual, attrs, manager, type_id in projects_data:
            ProjectRepository.create_on_connection(conn, project_id=pid, name=name, status=status,
                planned_budget=planned, actual_budget=actual, dynamic_attributes=attrs,
                function_id=manager, project_type_id=type_id)
        # Batch insert project tasks
        cursor.executemany(
            """
            INSERT INTO project_task (id, project_id, task_name, phase, start_date, end_date, progress_pct, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(task_id_base + i + 1, *row) for i, row in enumerate(milestones_data)],
        )

        # Batch insert task dependencies
        cursor.executemany(
            """
            INSERT INTO task_dependencies (task_id, predecessor_task_id, predecessor_project_id, link_type, lag_days)
            VALUES (?, ?, ?, ?, ?)
            """,
            dependencies_data,
        )

        pools = [r[0] for r in conn.execute("SELECT id FROM resource_pool ORDER BY id")]
        project_tags = [r[0] for r in conn.execute("SELECT d.id FROM tag_dictionnary d JOIN tag_group g ON g.id=d.tag_group_id WHERE g.tag_group_name='project_tag' ORDER BY d.id")]
        task_tags = [r[0] for r in conn.execute("SELECT d.id FROM tag_dictionnary d JOIN tag_group g ON g.id=d.tag_group_id WHERE g.tag_group_name='Task_Tag' ORDER BY d.id")]
        for i, pid in enumerate(project_ids):
            if pools:
                conn.execute("INSERT INTO resource_pool_assignment(pool_id,project_id,fte_assigned,notes) VALUES (?,?,1.0,'Demo allocation')", (pools[i % len(pools)], pid))
            if project_tags:
                conn.execute("INSERT INTO project_tag(project_id,tag_id) VALUES (?,?)", (pid, project_tags[i % len(project_tags)]))
        for i in range(len(milestones_data)):
            if task_tags:
                conn.execute("INSERT INTO task_tag(task_id,tag_id) VALUES (?,?)", (task_id_base+i+1, task_tags[i % len(task_tags)]))
        property_count = sum(conn.execute("SELECT COUNT(*) FROM project_property_value WHERE project_id=?", (pid,)).fetchone()[0] for pid in project_ids)
        type_count = conn.execute("SELECT COUNT(*) FROM project_type").fetchone()[0]
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")

    from scripts.seed_pool_scenarios import seed_pool_scenarios
    with closing(get_db(db_path)) as conn, conn:
        has_demo_organization = bool(conn.execute(
            "SELECT 1 FROM schema_migration WHERE version='demo-bootstrap-v1'"
        ).fetchone())
    if has_demo_organization:
        pool_summary = seed_pool_scenarios(db_path)
    else:
        # Append mode also supports reference-only, user-defined catalogs.
        # Do not inject demo employees or pools into those organizations.
        logger.info("Pool scenarios skipped: existing custom catalog has no demo organization.")
        pool_summary = {"new_pools": 0, "new_groups": 0}
    elapsed = time.time() - start_time
    summary = {
        "projects_created": len(projects_data),
        "project_types": type_count,
        "property_values_created": property_count,
        "tasks_created": len(milestones_data),
        "dependencies_created": len(dependencies_data),
        "pools_created": pool_summary["new_pools"],
        "pool_groups_created": pool_summary["new_groups"],
    }

    logger.info(
        "Seeding completed in %.2fs: %d projects, %d tasks, %d dependencies generated.",
        elapsed,
        summary["projects_created"],
        summary["tasks_created"],
        summary["dependencies_created"],
    )
    return summary


def main() -> None:
    """CLI entrypoint for database seed script."""
    parser = argparse.ArgumentParser(description="Seed the EPPM database with realistic projects and tasks.")
    parser.add_argument(
        "--projects",
        type=int,
        default=1000,
        help="Number of projects to generate (default: 1000).",
    )
    parser.add_argument(
        "--min-tasks",
        type=int,
        default=0,
        help="Minimum tasks per project (default: 0).",
    )
    parser.add_argument(
        "--max-tasks",
        type=int,
        default=15,
        help="Maximum tasks per project (default: 15).",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Optional path to SQLite database file.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        default=True,
        help="Flush existing records and execute seeder.py before generating projects (default: True).",
    )
    parser.add_argument(
        "--no-clean",
        action="store_false",
        dest="clean",
        help="Do not flush existing records before seeding.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible generation (default: 42).",
    )

    args = parser.parse_args()

    print("==================================================")
    print(f"[*] Seeding EPPM Database ({args.projects} projects, {args.min_tasks}-{args.max_tasks} tasks/project)...")
    print("==================================================")

    res = seed_database(
        num_projects=args.projects,
        min_tasks_per_project=args.min_tasks,
        max_tasks_per_project=args.max_tasks,
        db_path=args.db_path,
        clean_first=args.clean,
        random_seed=args.seed,
    )

    print("--------------------------------------------------")
    print("[+] Seeding Finished Successfully:")
    print(f"   - Projects Created:     {res['projects_created']:,}")
    print(f"   - Tasks Created:        {res['tasks_created']:,}")
    print(f"   - Dependencies Created: {res['dependencies_created']:,}")
    print(f"   - Project Types:        {res['project_types']:,}")
    print(f"   - Property Values:      {res['property_values_created']:,}")
    print("--------------------------------------------------")


if __name__ == "__main__":
    main()

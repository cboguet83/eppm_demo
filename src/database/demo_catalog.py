"""Shared project-type demo catalog and template-aware sample value factory."""

import random

from src.database.property_store import effective_template, write_value
from src.repositories.project_repo import ProjectRepository


DEMO_TYPES = ("General", "Infrastructure", "Digitalisation", "Compliance", "Renovation")
SCOPE_DEFAULTS = {
    "Infrastructure": "Design and delivery of railway infrastructure improvements",
    "Digitalisation": "Digitise workflows and integrate enterprise information systems",
    "Compliance": "Assess regulatory obligations and implement corrective actions",
}


def install_type_catalog(conn) -> None:
    """Only called while installing a fresh demo catalog, never on ordinary reload."""
    for name in DEMO_TYPES[1:]:
        conn.execute("INSERT INTO project_type(name,description) VALUES (?,?)", (name, f"{name} projects"))
    ids = dict(conn.execute("SELECT name,id FROM project_type"))
    conn.execute("UPDATE schema_parameters SET mandatory=1 WHERE param_id='PRM_011'")
    for pid, group in conn.execute("SELECT param_id,group_id FROM schema_parameters").fetchall():
        applicable = ("Infrastructure", "Renovation") if group == 3 else ("Infrastructure", "Digitalisation", "Renovation") if pid == "PRM_015" else None
        if applicable:
            conn.execute("UPDATE schema_parameters SET applies_to_all=0 WHERE param_id=?", (pid,))
            conn.executemany("INSERT INTO project_type_property(project_type_id,param_id) VALUES (?,?)", [(ids[name], pid) for name in applicable])
    for name, pid, required in [("General", "PRM_011", False), ("Infrastructure", "PRM_017", True), ("Compliance", "PRM_010", True)]:
        conn.execute("INSERT INTO project_type_property_rule(project_type_id,param_id,mandatory_override) VALUES (?,?,?)", (ids[name], pid, required))
    for name, value in SCOPE_DEFAULTS.items():
        write_value(conn, ids[name], "PRM_011", value, defaults=True)


def sample_values(conn, type_id: int, index: int, rng: random.Random, *, template=None, options=None) -> dict:
    """Generate only applicable values from the actual persisted definitions."""
    template = effective_template(conn, type_id) if template is None else template
    if options is None:
        options = {}
        for pid, value in conn.execute("SELECT param_id,option_value FROM schema_param_options ORDER BY display_order,id"):
            options.setdefault(pid, []).append(value)
    text_samples = {
        "PRM_001": f"CR-2026-{index:04d}", "PRM_002": "Modernise services and improve operational reliability",
        "PRM_003": "Steering committee review scheduled", "PRM_006": "Lot 1",
        "PRM_009": "Reduce delays and improve service quality", "PRM_010": "Acceptance tests passed and sponsor sign-off recorded",
        "PRM_011": "Delivery, verification, and operational handover", "PRM_012": "Unrelated legacy systems",
        "PRM_013": "Supplier lead times", "PRM_014": "Sponsor, operations, engineering",
        "PRM_015": "ERP, reporting, and operational systems", "PRM_020": "Northern section",
        "PRM_021": "Luxembourg", "PRM_022": "PK 0+000", "PRM_023": "PK 14+500",
    }
    result = {}
    for p in template:
        pid, kind = p["param_id"], p["param_type"]
        # Some examples use defaults, others explicitly override them.
        if p["has_default"] and index % 2:
            continue
        choices = options.get(pid, [])
        if kind in ("ENUM", "MULTI_ENUM", "TAGS"):
            if not choices:
                if p["mandatory"]:
                    raise ValueError(f"Cannot seed required property {pid}: no configured options")
                continue
            result[pid] = rng.choice(choices) if kind == "ENUM" else rng.sample(choices, min(2, len(choices)))
        elif kind == "NUMBER":
            result[pid] = round(rng.uniform(49.44, 50.18), 4) if pid == "PRM_018" else round(rng.uniform(5.73, 6.53), 4)
        elif kind == "DATE":
            result[pid] = "2026-12-31" if pid == "PRM_005" else "2026-01-10"
        elif kind in ("URL", "HYPERLINK"):
            result[pid] = f"https://example.org/projects/{index}/{pid}"
        else:
            result[pid] = text_samples.get(pid, f"{p['param_name']} — example {index}")
    return result


def seed_sample_projects(conn) -> None:
    """Five curated projects and schedules, with actual generated references."""
    ids = dict(conn.execute("SELECT name,id FROM project_type"))
    managers = [r[0] for r in conn.execute("SELECT function_id FROM function ORDER BY function_id")]
    samples = [
        ("Digitalisation", "NextGen ERP Modernization", 450000.0, 380000.0),
        ("Infrastructure", "Northern Rail Capacity Upgrade", 280000.0, 210000.0),
        ("Compliance", "Global Supply Chain Audit", 150000.0, 142000.0),
        ("Renovation", "Central Station Renovation", 320000.0, 100000.0),
        ("General", "Portfolio Governance Review", 50000.0, 10000.0),
    ]
    rng = random.Random(42)
    last_project = last_task = None
    for index, (type_name, name, planned, actual) in enumerate(samples, 1):
        type_id = ids[type_name]
        pid = ProjectRepository.create_on_connection(conn, name=name, status="Completed" if type_name == "Compliance" else "In Progress",
            planned_budget=planned, actual_budget=actual, project_type_id=type_id,
            function_id=managers[(index + 15) % len(managers)] if managers else None,
            dynamic_attributes=sample_values(conn, type_id, index, rng))
        previous = None
        for task_name, phase, start, end, progress in [
            ("Architecture & Scoping", "FAI", "2026-01-10", "2026-02-15", 100),
            ("Delivery", "EXE", "2026-02-16", "2026-06-30", 60),
            ("Acceptance", "DEF", "2026-07-01", "2026-09-15", 0),
        ]:
            task_id = conn.execute("INSERT INTO project_task(project_id,task_name,phase,start_date,end_date,progress_pct) VALUES (?,?,?,?,?,?)",
                (pid, task_name, phase, start, end, 100 if type_name == "Compliance" else progress)).lastrowid
            if previous:
                conn.execute("INSERT INTO task_dependencies(task_id,predecessor_task_id,link_type,lag_days) VALUES (?,?,'FS',0)", (task_id, previous))
            elif last_task:
                conn.execute("INSERT INTO task_dependencies(task_id,predecessor_task_id,predecessor_project_id,link_type,lag_days) VALUES (?,?,?,'SS',0)", (task_id, last_task, last_project))
            previous = task_id
        last_project, last_task = pid, previous

"""Database Seeding Utility.

Populates the EPPM database with realistic projects, hierarchical milestone schedules,
and rich internal and external task dependencies.
"""

import argparse
import datetime
import json
import os
import random
import sys
import time
from typing import Any, Optional

# Ensure project root is in sys.path when running script directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.flush_database import flush_database
from src.database.connection import get_db
from src.database.schema_init import init_db
from src.database.seeder import (
    DEFAULT_CATEGORY_OPTIONS,
    DEFAULT_COMPLEXITY_OPTIONS,
    DEFAULT_LINE_OPTIONS,
    DEFAULT_PHASE_OPTIONS,
    DEFAULT_STATION_OPTIONS,
    DEFAULT_STATUS_OPTIONS,
    DEFAULT_STRATEGIC_PRIORITY_OPTIONS,
    seed_default_data_if_empty,
)
from src.logging_config import get_logger

logger = get_logger(__name__)

# Sample Data Dictionaries for Realistic Generation
PROJECT_THEMES: list[str] = [
    "Projet Infra",
    "Projet Digitalisation",
    "Mise ne conformité",
    "Projet Rénovation",
    "Autre Projet",
]

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

PROJECT_STATUSES: list[str] = [
    "Active", "Active", "Active", "Planned", "Planned", "In Review", "Completed", "On Hold", "Draft"
]

LINK_TYPES: list[str] = ["FS", "FS", "FS", "SS", "FF", "SF"]

DYNAMIC_CATEGORIES: list[str] = ["Stratégique", "Opérationnel", "Conformité", "Innovation", "Infrastructure"]
DYNAMIC_PRIORITIES: list[str] = ["Critique", "Haut", "Moyen", "Bas"]
DYNAMIC_DEPARTMENTS: list[str] = ["Service A", "Service B", "Service C", "Service D", "Service E", "Global"]
DYNAMIC_RISKS: list[str] = ["High", "Medium", "Low"]


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
    if random_seed is not None:
        random.seed(random_seed)

    start_time = time.time()
    logger.info("Initializing database and preparing seeding for %d projects...", num_projects)

    init_db(db_path)

    if clean_first:
        flush_database(db_path, flush_all=True)

    # Execute default data seeder (populates schema groups, parameters, organization hierarchy, functions, employees)
    seed_default_data_if_empty(db_path)

    # Clean default bootstrap sample projects (1, 2, 3) so only generated projects are populated
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM task_dependencies 
            WHERE predecessor_project_id IN (1, 2, 3)
               OR task_id IN (SELECT id FROM project_task WHERE project_id IN (1, 2, 3))
               OR predecessor_task_id IN (SELECT id FROM project_task WHERE project_id IN (1, 2, 3))
            """
        )
        cursor.execute("UPDATE project_task SET predecessor_id = NULL WHERE project_id IN (1, 2, 3)")
        cursor.execute("DELETE FROM project_task WHERE project_id IN (1, 2, 3)")
        cursor.execute("DELETE FROM project WHERE id IN (1, 2, 3)")
        conn.commit()

    # 1. Build Projects Payload
    projects_data: list[tuple[int, str, str, float, float, str, int]] = []
    project_ids: list[int] = []
    base_start_date = datetime.date(2025, 6, 1)

    for i in range(1, num_projects + 1):
        p_id = i
        project_ids.append(p_id)

        theme = random.choice(PROJECT_THEMES)
        suffix = random.choice(PROJECT_SUFFIXES)
        p_name = f"{theme} ({suffix} #{i})"
        p_status = random.choice(PROJECT_STATUSES)

        planned_budget = round(random.uniform(50_000, 3_000_000), 2)
        if p_status == "Completed":
            actual_budget = round(planned_budget * random.uniform(0.85, 1.15), 2)
        elif p_status == "Active":
            actual_budget = round(planned_budget * random.uniform(0.20, 0.85), 2)
        elif p_status in ("In Review", "On Hold"):
            actual_budget = round(planned_budget * random.uniform(0.05, 0.40), 2)
        else:  # Draft, Planned
            actual_budget = round(planned_budget * random.uniform(0.0, 0.05), 2)

        p_offset_days = random.randint(0, 365)
        p_start_date = base_start_date + datetime.timedelta(days=p_offset_days)
        p_stop_date = p_start_date + datetime.timedelta(days=random.randint(90, 730))
        station_opt = random.choice(DEFAULT_STATION_OPTIONS)
        line_opt = random.choice(DEFAULT_LINE_OPTIONS)
        pm_function_id = random.randint(17, 26)

        dyn_attrs = {
            "code courrier": f"CR-2026-{i:04d}",
            "description": f"{theme} implementation and rollout for {suffix} #{i}",
            "commentaire": random.choice(["On track", "Steerco approval pending", "Review scheduled", "Specification completed", "In execution"]),
            "start_date": p_start_date.isoformat(),
            "stop_Date": p_stop_date.isoformat(),
            "lot": f"Lot {random.randint(1, 5)}",
            "phase": random.choice(DEFAULT_PHASE_OPTIONS),
            "benefits": f"Improves operational efficiency for {theme} and delivers measurable ROI.",
            "acceptance_ctriteria": "Validation tests passing and acceptance signed by technical leads.",
            "scope": f"End-to-end execution of {theme} across designated divisions.",
            "out_of_scope": "Secondary third-party vendor extensions and legacy integrations.",
            "risks": random.choice(["Resource availability constraint", "Timeline dependency delay", "Vendor integration latency", "Low risk"]),
            "stakeholders": "Project Sponsor, Division Head, Operations Manager",
            "interfaces": "Internal API, ERP Connector, Reporting Data Warehouse",
            "code_station": station_opt,
            "code_line": line_opt,
            "lat": round(random.uniform(49.44, 50.18), 4),
            "long": round(random.uniform(5.73, 6.53), 4),
            "section": f"Section {random.choice(['Alpha', 'Beta', 'Gamma', 'Delta', 'Nord', 'Sud', 'Est', 'Ouest'])}",
            "station": station_opt.split()[0],
            "pk_start": f"PK {random.randint(0, 50)}+{random.randint(0, 999):03d}",
            "pk_stop": f"PK {random.randint(51, 120)}+{random.randint(0, 999):03d}",
            "acc_link": f"https://eppm.enterprise.internal/acc/PRJ-{i:04d}",
            "pb_link": f"https://jira.enterprise.internal/browse/PRJ-{i:04d}",
            "orga_link": f"https://confluence.enterprise.internal/wiki/PRJ-{i:04d}",
            "strategic_priority": random.choice(DEFAULT_STRATEGIC_PRIORITY_OPTIONS),
            "category": random.choice(DEFAULT_CATEGORY_OPTIONS),
            "category_tags": random.sample(["Core", "Strategic", "Cloud Native", "Infrastructure", "Modernization", "Compliance", "Digital"], k=random.randint(1, 3)),
            "complexity": random.choice(DEFAULT_COMPLEXITY_OPTIONS),
        }

        projects_data.append((
            p_id,
            p_name,
            p_status,
            planned_budget,
            actual_budget,
            json.dumps(dyn_attrs),
            pm_function_id,
        ))

    # 2. Build Tasks / Milestones Payload
    # Structure: [(project_id, task_name, phase, start_date, end_date, progress_pct, description)]
    milestones_data: list[tuple[int, str, str, str, str, int, str]] = []
    project_task_indices: dict[int, list[int]] = {p_id: [] for p_id in project_ids}
    project_task_id_by_code: dict[int, dict[str, int]] = {p_id: {} for p_id in project_ids}
    global_task_counter = 0

    # Store planned task dates for dependency validation
    task_date_map: dict[int, tuple[datetime.date, datetime.date, int]] = {}

    standard_tasks_type2 = [tmpl for tmpl in TASK_TEMPLATES if tmpl[0] != "N/A"]

    for p_idx, p_id in enumerate(project_ids):
        p_status = projects_data[p_idx][2]
        p_offset_days = random.randint(0, 365)
        cur_date = base_start_date + datetime.timedelta(days=p_offset_days)

        if max_tasks_per_project == 0:
            continue

        # Decide between Project Type 1 and Project Type 2 based on task bounds
        can_be_type_1 = (min_tasks_per_project <= 1 <= max_tasks_per_project)
        can_be_type_2 = (max_tasks_per_project >= 2) or (min_tasks_per_project == 0 and max_tasks_per_project >= 1)

        if can_be_type_1 and not can_be_type_2:
            is_type_1 = True
        elif can_be_type_2 and not can_be_type_1:
            is_type_1 = False
        else:
            is_type_1 = random.random() < 0.20

        if is_type_1:
            # =================================================================
            # Project Type 1: Only 1 N/A phase (3 months to 3 years)
            # =================================================================
            duration_days = random.randint(90, 1095)
            task_start = cur_date
            task_end = task_start + datetime.timedelta(days=duration_days)

            if p_status == "Completed":
                prog_pct = 100
            elif p_status in ("Draft", "Planned"):
                prog_pct = 0
            else:
                prog_pct = random.choice([0, 25, 50, 75, 100])

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
            # Project Type 2: All standard tasks (FAI, APS, APD1, APD2, EXE, CHA, DEF)
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
                num_milestones = random.randint(min_m, max_m)
            elif max_m > 0:
                num_milestones = max_m
            else:
                num_milestones = 0

            chosen_milestones = random.sample(MILESTONE_TEMPLATES, k=num_milestones) if num_milestones > 0 else []

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

            # Sort items chronologically by start date
            task_items.sort(key=lambda x: (x["start"], 0 if not x["is_milestone"] else 1))

            # Determine progress across the project lifecycle
            num_items = len(task_items)
            active_index = random.randint(0, num_items - 1) if num_items > 0 else 0

            for idx, item in enumerate(task_items):
                global_task_counter += 1

                if p_status == "Completed":
                    prog_pct = 100
                elif p_status in ("Draft", "Planned"):
                    prog_pct = 0
                elif p_status == "Active":
                    if idx < active_index:
                        prog_pct = 100
                    elif idx == active_index:
                        prog_pct = 100 if item["is_milestone"] else random.choice([25, 50, 75])
                    else:
                        prog_pct = 0
                else:
                    prog_pct = random.choice([0, 0, 25, 50, 75, 100])

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
        if p_idx > 0 and random.random() < 0.22:
            first_task_id = p_task_ids[0]
            ext_p_idx = random.randint(0, p_idx - 1)
            ext_p_id = project_ids[ext_p_idx]
            ext_p_tasks = project_task_indices[ext_p_id]

            if random.random() < 0.40 or not ext_p_tasks:
                dependencies_data.append((
                    first_task_id,
                    None,
                    ext_p_id,
                    random.choice(["FS", "SS"]),
                    random.choice([0, 2, 5]),
                ))
            else:
                ext_pred_task_id = random.choice(ext_p_tasks)
                dependencies_data.append((
                    first_task_id,
                    ext_pred_task_id,
                    ext_p_id,
                    random.choice(["FS", "SS", "FF"]),
                    random.choice([0, 1, 3]),
                ))

    # 4. Fast SQLite Transaction Execution
    with get_db(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        cursor = conn.cursor()

        # Batch insert projects
        cursor.executemany(
            """
            INSERT OR REPLACE INTO project (id, name, status, planned_budget, actual_budget, dynamic_attributes, function_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            projects_data,
        )

        # Batch insert project tasks
        cursor.executemany(
            """
            INSERT INTO project_task (project_id, task_name, phase, start_date, end_date, progress_pct, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            milestones_data,
        )

        # Batch insert task dependencies
        cursor.executemany(
            """
            INSERT INTO task_dependencies (task_id, predecessor_task_id, predecessor_project_id, link_type, lag_days)
            VALUES (?, ?, ?, ?, ?)
            """,
            dependencies_data,
        )

        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")

    elapsed = time.time() - start_time
    summary = {
        "projects_created": len(projects_data),
        "tasks_created": len(milestones_data),
        "dependencies_created": len(dependencies_data),
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
    print("--------------------------------------------------")


if __name__ == "__main__":
    main()

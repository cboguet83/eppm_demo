"""Database Seeding Utility.

Populates the EPPM database with realistic projects, hierarchical milestone schedules,
and rich internal and external task dependencies.
"""

import argparse
import datetime
import json
import random
import time
from typing import Any, Optional

from src.database.connection import get_db
from src.database.schema_init import init_db
from src.logging_config import get_logger

logger = get_logger(__name__)

# Sample Data Dictionaries for Realistic Generation
PROJECT_THEMES: list[str] = [
    "Infrastructure Projects",
    "Modernization Projects",
    "Energy Project",
    "Electronic Project",
    "Other Project",
]

PROJECT_SUFFIXES: list[str] = [
    "Phase 1", "Phase 2", "Rollout", "Upgrade", "NextGen", "Pilot", "Core", "Revamp",
    "Modernization", "Global Expansion", "Wave A", "Wave B", "Platform", "Sync",
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

PROJECT_STATUSES: list[str] = [
    "Active", "Active", "Active", "Planned", "Planned", "In Review", "Completed", "On Hold", "Draft"
]

LINK_TYPES: list[str] = ["FS", "FS", "FS", "SS", "FF", "SF"]

DYNAMIC_CATEGORIES: list[str] = ["Strategic", "Operational", "Compliance", "Innovation", "Infrastructure"]
DYNAMIC_PRIORITIES: list[str] = ["Critical", "High", "Medium", "Low"]
DYNAMIC_DEPARTMENTS: list[str] = ["Engineering", "Product", "Operations", "Finance", "Marketing", "Security"]
DYNAMIC_RISKS: list[str] = ["High", "Medium", "Low"]


def seed_database(
    num_projects: int = 500,
    min_tasks_per_project: int = 0,
    max_tasks_per_project: int = 25,
    db_path: Optional[str] = None,
    clean_first: bool = False,
    random_seed: Optional[int] = 42,
) -> dict[str, int]:
    """Generates and seeds projects, tasks, and dependency links into SQLite.

    Args:
        num_projects: Total number of projects to generate. Default 500.
        min_tasks_per_project: Minimum tasks per project (>=0). Default 0.
        max_tasks_per_project: Maximum tasks per project (<=50). Default 25.
        db_path: Optional SQLite database path.
        clean_first: If True, wipes existing projects before seeding.
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
        from scripts.flush_database import flush_database
        flush_database(db_path)

    # 1. Build Projects Payload
    projects_data: list[tuple[str, str, str, float, float, str]] = []
    project_ids: list[str] = []
    base_start_date = datetime.date(2025, 6, 1)

    for i in range(1, num_projects + 1):
        p_id = f"PRJ-{i:04d}"
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
        else: # Draft, Planned
            actual_budget = round(planned_budget * random.uniform(0.0, 0.05), 2)

        dyn_attrs = {
            "Category": random.choice(DYNAMIC_CATEGORIES),
            "Priority": random.choice(DYNAMIC_PRIORITIES),
            "Business Unit": random.choice(DYNAMIC_DEPARTMENTS),
            "Risk Level": random.choice(DYNAMIC_RISKS),
        }

        projects_data.append((
            p_id,
            p_name,
            p_status,
            planned_budget,
            actual_budget,
            json.dumps(dyn_attrs),
        ))

    # 2. Build Tasks / Milestones Payload
    # Structure: [(project_id, task_name, phase, start_date, end_date, progress_pct)]
    milestones_data: list[tuple[str, str, str, str, str, int]] = []
    project_task_indices: dict[str, list[int]] = {p_id: [] for p_id in project_ids}
    global_task_counter = 0

    # Store planned task dates for dependency validation
    # global_task_counter -> (start_date_str, end_date_str, project_id)
    task_date_map: dict[int, tuple[datetime.date, datetime.date, str]] = {}

    for p_id in project_ids:
        task_count = random.randint(min_tasks_per_project, max_tasks_per_project)
        p_offset_days = random.randint(0, 365)
        cur_date = base_start_date + datetime.timedelta(days=p_offset_days)

        # Select task templates in sequential lifecycle order
        if task_count <= len(TASK_TEMPLATES):
            chosen_templates = TASK_TEMPLATES[:task_count]
        else:
            chosen_templates = []
            while len(chosen_templates) < task_count:
                for tmpl in TASK_TEMPLATES:
                    if len(chosen_templates) < task_count:
                        chosen_templates.append(tmpl)

        # Track duplicates to add suffix if needed
        name_counts: dict[str, int] = {}
        for tmpl in chosen_templates:
            name_counts[tmpl[0]] = name_counts.get(tmpl[0], 0) + 1

        name_indices: dict[str, int] = {}
        for t_idx, (t_name, t_phase) in enumerate(chosen_templates):
            global_task_counter += 1
            name_indices[t_name] = name_indices.get(t_name, 0) + 1
            if name_counts[t_name] > 1:
                display_name = f"{t_name} ({name_indices[t_name]})"
            else:
                display_name = t_name

            is_milestone = t_name in ("DEF", "N/A") or random.random() < 0.10
            
            task_start = cur_date
            if is_milestone:
                task_end = task_start
                cur_date = task_start + datetime.timedelta(days=random.randint(1, 4))
            else:
                duration = random.randint(5, 30)
                task_end = task_start + datetime.timedelta(days=duration)
                cur_date = task_end + datetime.timedelta(days=random.randint(0, 5))

            prog_pct = random.choice([0, 0, 25, 50, 75, 100, 100])

            milestones_data.append((
                p_id,
                display_name,
                t_phase,
                task_start.isoformat(),
                task_end.isoformat(),
                prog_pct,
            ))

            project_task_indices[p_id].append(global_task_counter)
            task_date_map[global_task_counter] = (task_start, task_end, p_id)

    # 3. Build Dependencies Payload (Internal & External Links)
    # Structure: [(task_id, predecessor_task_id, predecessor_project_id, link_type, lag_days)]
    dependencies_data: list[tuple[int, Optional[int], Optional[str], str, int]] = []

    for p_idx, p_id in enumerate(project_ids):
        p_task_ids = project_task_indices[p_id]
        if not p_task_ids:
            continue

        # A. Internal Dependencies within Project
        for i in range(1, len(p_task_ids)):
            curr_task_id = p_task_ids[i]
            # 60% probability of linking to an earlier task
            if random.random() < 0.60:
                pred_task_id = p_task_ids[random.randint(0, i - 1)]
                link_type = random.choice(LINK_TYPES)
                lag_days = random.choice([-2, 0, 0, 1, 3, 5])
                dependencies_data.append((
                    curr_task_id,
                    pred_task_id,
                    None,
                    link_type,
                    lag_days,
                ))

        # B. External Dependencies across Projects (for ~20% of projects)
        if p_idx > 0 and random.random() < 0.22:
            first_task_id = p_task_ids[0]
            # Pick an earlier project
            ext_p_idx = random.randint(0, p_idx - 1)
            ext_p_id = project_ids[ext_p_idx]
            ext_p_tasks = project_task_indices[ext_p_id]

            if random.random() < 0.40 or not ext_p_tasks:
                # Link to whole external project
                dependencies_data.append((
                    first_task_id,
                    None,
                    ext_p_id,
                    random.choice(["FS", "SS"]),
                    random.choice([0, 2, 5]),
                ))
            else:
                # Link to a specific task in the external project
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
            INSERT OR REPLACE INTO projects (id, name, status, planned_budget, actual_budget, dynamic_attributes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            projects_data,
        )

        # Batch insert project milestones
        cursor.executemany(
            """
            INSERT INTO project_milestones (project_id, task_name, phase, start_date, end_date, progress_pct)
            VALUES (?, ?, ?, ?, ?, ?)
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
        default=500,
        help="Number of projects to generate (default: 500).",
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
        default=25,
        help="Maximum tasks per project (default: 25).",
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
        help="Flush existing project data before seeding.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible generation (default: 42).",
    )

    args = parser.parse_args()

    print("==================================================")
    print(f"🚀 Seeding EPPM Database ({args.projects} projects, {args.min_tasks}-{args.max_tasks} tasks/project)...")
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
    print("✅ Seeding Finished Successfully:")
    print(f"   • Projects Created:     {res['projects_created']:,}")
    print(f"   • Tasks Created:        {res['tasks_created']:,}")
    print(f"   • Dependencies Created: {res['dependencies_created']:,}")
    print("--------------------------------------------------")


if __name__ == "__main__":
    main()

"""Default demo data seeder for PPM Studio Pro."""

import json
from typing import Optional

from src.config import config
from src.database.connection import get_db
from src.logging_config import get_logger
from src.models.constants import (
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
)

logger = get_logger(__name__)


def seed_default_data_if_empty(db_path: Optional[str] = None) -> None:
    """Populates the database with demo schema, projects, and milestones if empty.

    Args:
        db_path: Filepath to the SQLite database. If None, uses default from config.
    """
    target_path = db_path if db_path is not None else config.db_path
    logger.info("Checking if database seeding is required for %s", target_path)

    with get_db(target_path) as conn:
        cursor = conn.cursor()

        # Check Schema Groups
        cursor.execute("SELECT COUNT(*) FROM schema_groups")
        group_count = cursor.fetchone()[0]

        if group_count == 0:
            logger.info("Seeding default schema groups and parameters...")
            cursor.execute("INSERT OR IGNORE INTO schema_groups (id, group_name, display_order) VALUES (1, 'Strategic Alignment', 1)")
            cursor.execute("INSERT OR IGNORE INTO schema_groups (id, group_name, display_order) VALUES (2, 'Governance & Architecture', 2)")

            cursor.execute("INSERT OR IGNORE INTO schema_parameters (param_id, group_id, param_name, param_type) VALUES ('PRM_001', 1, 'Strategic Priority', 'ENUM')")
            cursor.execute("INSERT OR IGNORE INTO schema_parameters (param_id, group_id, param_name, param_type) VALUES ('PRM_002', 1, 'Business Unit', 'ENUM')")
            cursor.execute("INSERT OR IGNORE INTO schema_parameters (param_id, group_id, param_name, param_type) VALUES ('PRM_003', 2, 'Tech Stack Tags', 'TAGS')")
            cursor.execute("INSERT OR IGNORE INTO schema_parameters (param_id, group_id, param_name, param_type) VALUES ('PRM_004', 2, 'Repository URL', 'URL')")
            cursor.execute("INSERT OR IGNORE INTO schema_parameters (param_id, group_id, param_name, param_type) VALUES ('PRM_005', 2, 'Lead Architect', 'TEXT')")
            cursor.execute("INSERT OR IGNORE INTO schema_parameters (param_id, group_id, param_name, param_type) VALUES ('PRM_006', NULL, 'General Keywords', 'TAGS')")

            prm_001_opts = ["P1 - Critical", "P2 - High", "P3 - Medium", "P4 - Low"]
            for idx, opt in enumerate(prm_001_opts, 1):
                cursor.execute("INSERT INTO schema_param_options (param_id, option_value, display_order) VALUES ('PRM_001', ?, ?)", (opt, idx))

            prm_002_opts = ["Engineering", "Product", "Operations", "Finance", "Marketing"]
            for idx, opt in enumerate(prm_002_opts, 1):
                cursor.execute("INSERT INTO schema_param_options (param_id, option_value, display_order) VALUES ('PRM_002', ?, ?)", (opt, idx))

            prm_003_opts = ["Python", "React", "Cloud Native", "AI/ML", "Kubernetes", "PostgreSQL"]
            for idx, opt in enumerate(prm_003_opts, 1):
                cursor.execute("INSERT INTO schema_param_options (param_id, option_value, display_order) VALUES ('PRM_003', ?, ?)", (opt, idx))

        # Check Projects
        cursor.execute("SELECT id FROM projects")
        existing_pids = {row[0] for row in cursor.fetchall()}

        sample_projects = [
            (
                "PRJ-001",
                "NextGen ERP Modernization",
                STATUS_IN_PROGRESS,
                450000.0,
                380000.0,
                json.dumps({
                    "PRM_001": "P1 - Critical",
                    "PRM_002": "Engineering",
                    "PRM_003": ["Python", "Cloud Native", "Kubernetes"],
                    "PRM_004": "https://github.com/enterprise/erp-modernization",
                    "PRM_005": "Dr. Sarah Connor",
                    "PRM_006": ["Core", "2026-Priority"],
                }),
            ),
            (
                "PRJ-002",
                "Customer 360 AI Analytics",
                STATUS_IN_PROGRESS,
                280000.0,
                310000.0,
                json.dumps({
                    "PRM_001": "P1 - Critical",
                    "PRM_002": "Product",
                    "PRM_003": ["Python", "AI/ML"],
                    "PRM_004": "https://github.com/enterprise/c360-ai",
                    "PRM_005": "Alex Chen",
                    "PRM_006": ["AI", "Analytics"],
                }),
            ),
            (
                "PRJ-003",
                "Global Supply Chain Audit",
                STATUS_COMPLETED,
                150000.0,
                142000.0,
                json.dumps({
                    "PRM_001": "P2 - High",
                    "PRM_002": "Operations",
                    "PRM_003": ["Cloud Native"],
                    "PRM_004": "https://docs.enterprise.internal/audit",
                    "PRM_005": "Elena Rostova",
                    "PRM_006": ["Compliance"],
                }),
            ),
        ]

        if not existing_pids:
            logger.info("Seeding sample projects...")
            cursor.executemany(
                "INSERT INTO projects (id, name, status, planned_budget, actual_budget, dynamic_attributes) VALUES (?, ?, ?, ?, ?, ?)",
                sample_projects,
            )
            cursor.execute("SELECT id FROM projects")
            existing_pids = {row[0] for row in cursor.fetchall()}

        # Check Milestones
        cursor.execute("SELECT COUNT(*) FROM project_milestones")
        milestone_count = cursor.fetchone()[0]

        if milestone_count == 0:
            logger.info("Seeding sample project steps and milestones...")
            if "PRJ-001" in existing_pids:
                cursor.execute(
                    "INSERT INTO project_milestones (id, project_id, task_name, phase, start_date, end_date, progress_pct, predecessor_id) VALUES (1, 'PRJ-001', 'Architecture & Scoping', 'Phase 1 - Inception', '2026-01-10', '2026-02-15', 100, NULL)"
                )
                cursor.execute(
                    "INSERT INTO project_milestones (id, project_id, task_name, phase, start_date, end_date, progress_pct, predecessor_id) VALUES (2, 'PRJ-001', 'Architecture Sign-Off', 'Phase 1 - Inception', '2026-02-15', '2026-02-15', 100, 1)"
                )
                cursor.execute(
                    "INSERT INTO project_milestones (id, project_id, task_name, phase, start_date, end_date, progress_pct, predecessor_id) VALUES (3, 'PRJ-001', 'Core Microservices Dev', 'Phase 2 - Build', '2026-02-16', '2026-06-30', 75, 2)"
                )
                cursor.execute(
                    "INSERT INTO project_milestones (id, project_id, task_name, phase, start_date, end_date, progress_pct, predecessor_id) VALUES (4, 'PRJ-001', 'Integration & UAT', 'Phase 3 - Validation', '2026-07-01', '2026-09-15', 25, 3)"
                )
                cursor.execute(
                    "INSERT INTO project_milestones (id, project_id, task_name, phase, start_date, end_date, progress_pct, predecessor_id) VALUES (5, 'PRJ-001', 'Go-Live Release', 'Phase 4 - Rollout', '2026-09-15', '2026-09-15', 0, 4)"
                )

            if "PRJ-002" in existing_pids:
                cursor.execute(
                    "INSERT INTO project_milestones (project_id, task_name, phase, start_date, end_date, progress_pct, predecessor_id) VALUES ('PRJ-002', 'Data Pipeline Ingestion', 'Phase 1 - Data Eng', '2026-02-01', '2026-04-15', 100, NULL)"
                )
                cursor.execute(
                    "INSERT INTO project_milestones (project_id, task_name, phase, start_date, end_date, progress_pct, predecessor_id) VALUES ('PRJ-002', 'Model Training & Tuning', 'Phase 2 - ML Dev', '2026-04-16', '2026-07-30', 65, NULL)"
                )

            if "PRJ-003" in existing_pids:
                cursor.execute(
                    "INSERT INTO project_milestones (project_id, task_name, phase, start_date, end_date, progress_pct, predecessor_id) VALUES ('PRJ-003', 'Audit Execution', 'Phase 1 - Audit', '2026-02-11', '2026-04-20', 100, NULL)"
                )

        conn.commit()

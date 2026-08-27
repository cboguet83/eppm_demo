"""Default demo data seeder for PPM Studio Pro."""

import json
from typing import Optional

from src.config import config
from src.database.connection import get_db
from src.logging_config import get_logger
from src.models.constants import (
    PRIORITY_LIST,
    PRIORITY_P1_CRITICAL,
    PRIORITY_P2_HIGH,
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

            prm_001_opts = PRIORITY_LIST
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
                    "PRM_001": PRIORITY_P1_CRITICAL,
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
                    "PRM_001": PRIORITY_P1_CRITICAL,
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
                    "PRM_001": PRIORITY_P2_HIGH,
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

        # Check Organization Hierarchy Levels
        cursor.execute("SELECT COUNT(*) FROM hierarchy_level")
        hl_count = cursor.fetchone()[0]
        if hl_count == 0:
            logger.info("Seeding default hierarchy levels...")
            cursor.execute("INSERT INTO hierarchy_level (hierarchy_level_id, name, level, parent_hierarchy_level_id, manager_function_id) VALUES (1, 'Direction Générale', 1, NULL, NULL)")
            cursor.execute("INSERT INTO hierarchy_level (hierarchy_level_id, name, level, parent_hierarchy_level_id, manager_function_id) VALUES (2, 'Ressort', 2, 1, NULL)")
            cursor.execute("INSERT INTO hierarchy_level (hierarchy_level_id, name, level, parent_hierarchy_level_id, manager_function_id) VALUES (3, 'Service', 3, 2, NULL)")
            cursor.execute("INSERT INTO hierarchy_level (hierarchy_level_id, name, level, parent_hierarchy_level_id, manager_function_id) VALUES (4, 'Division', 4, 3, NULL)")
            cursor.execute("INSERT INTO hierarchy_level (hierarchy_level_id, name, level, parent_hierarchy_level_id, manager_function_id) VALUES (5, 'Equipe', 5, 4, NULL)")

        # Check Function Types
        cursor.execute("SELECT COUNT(*) FROM function_type")
        ft_count = cursor.fetchone()[0]
        if ft_count == 0:
            logger.info("Seeding default function types...")
            cursor.execute("INSERT INTO function_type (function_type_id, function_type) VALUES (1, 'Directeur Général')")
            cursor.execute("INSERT INTO function_type (function_type_id, function_type) VALUES (2, 'Directeur')")
            cursor.execute("INSERT INTO function_type (function_type_id, function_type) VALUES (3, 'Chef de Service')")
            cursor.execute("INSERT INTO function_type (function_type_id, function_type) VALUES (4, 'Chef de Division')")
            cursor.execute("INSERT INTO function_type (function_type_id, function_type) VALUES (5, 'Chef de Projet')")
            cursor.execute("INSERT INTO function_type (function_type_id, function_type) VALUES (6, 'Chargé de Projet')")
            cursor.execute("INSERT INTO function_type (function_type_id, function_type) VALUES (7, 'Assistant')")
            cursor.execute("INSERT INTO function_type (function_type_id, function_type) VALUES (8, 'BIM Manager')")
            cursor.execute("INSERT INTO function_type (function_type_id, function_type) VALUES (9, 'Ingénieur')")

        # Check Functions
        cursor.execute("SELECT COUNT(*) FROM function")
        func_count = cursor.fetchone()[0]
        if func_count == 0:
            logger.info("Seeding default job functions...")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (1, 'Directeur Général', 1, 1, NULL, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (2, 'Directeur Ressort 1', 2, 2, 1, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (3, 'Directeur Ressort 2', 2, 2, 1, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_ma3nager_function_id) VALUES (4, 'Chef de Service QSE', 2, 3, 1, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (5, 'Chef de Service A', 3, 3, 2, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (6, 'Chef de Service B', 3, 3, 2, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (7, 'Chef de Service C', 3, 3, 2, 2)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (8, 'Chef de Service D', 3, 3, 2, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (9, 'Chef de Service E', 3, 3, 2, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (10, 'Chef de Division A_1', 4, 4, 5, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (11, 'Chef de Division A_2', 4, 4, 5, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (12, 'Chef de Division A_3', 4, 4, 5, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (13, 'Chef de Division A_4', 4, 4, 5, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (14, 'Chef de Division B_1', 4, 4, 6, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (15, 'Chef de Division B_2', 4, 4, 6, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (16, 'Chef de Division B_3', 4, 4, 6, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (17, 'Chef de Projet A_1_A', 5, 5, 10, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (18, 'Chef de Projet A_1_B', 5, 5, 10, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (19, 'Chef de Projet A_1_C', 5, 5, 10, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (20, 'Chef de Projet A_1_D', 5, 5, 10, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (21, 'Chef de Projet A_1_E', 5, 5, 10, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (22, 'Chef de Projet A_2_F', 5, 5, 10, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (23, 'Chef de Projet A_2_G', 5, 5, 11, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (24, 'Chef de Projet A_2_H', 5, 5, 11, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (25, 'Chef de Projet A_2_J', 5, 5, 11, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (26, 'Chef de Projet A_2_K', 5, 5, 11, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (27, 'Chargé de Projet A_1_A1', 5, 6, 10, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (28, 'Chargé de Projet A_1_A2', 5, 6, 10, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (29, 'Chargé de Projet A_1_B1', 5, 6, 10, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (30, 'Chargé de Projet A_1_B2', 5, 6, 10, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (31, 'Chargé de Projet A_1_C', 5, 6, 10, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (32, 'Chargé de Projet A_1_D', 5, 6, 10, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (33, 'Chargé de Projet A_1_E', 5, 6, 10, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (34, 'Chargé de Projet A_2_F', 5, 6, 11, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (35, 'Chargé de Projet A_2_G', 5, 6, 12, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (36, 'Chargé de Projet A_2_H', 5, 6, 12, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (37, 'Chargé de Projet A_2_J', 5, 6, 12, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (38, 'Chargé de Projet A_2_K', 5, 6, 12, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (39, 'Chargé de Projet A_2_F', 5, 6, 12, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (40, 'Chargé de Projet A_2_G', 5, 6, 12, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (41, 'Chargé de Projet A_2_H', 5, 6, 12, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (42, 'Chargé de Projet A_2_J', 5, 6, 12, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (43, 'Chargé de Projet A_2_K', 5, 6, 12, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (44, 'Ingénieur B_1_1', 5, 9, 14, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (45, 'Ingénieur B_1_2', 5, 9, 14, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (46, 'Ingénieur B_2_1', 5, 9, 15, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (47, 'Assistant A_1_A', 5, 6, 10, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (48, 'Assistant A_1_B', 5, 6, 10, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (49, 'BIM Manager', 5, 8, 13, NULL)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level_id, function_type_id, manager_function_id, dual_manager_function_id) VALUES (50, 'BIM Assistant', 5, 7, 13, NULL)")
          

        # Check Employees
        cursor.execute("SELECT COUNT(*) FROM employee")
        emp_count = cursor.fetchone()[0]
        if emp_count == 0:
            logger.info("Seeding default employees...")
            sample_employees = [
                (1, "Louis", "Pasteur", "lpasteur@enterprise.com", "+352 621 123 456", "ABC_1", "1", 2),
                (2, "Henri", "Poincaré", "hpoincare@enterprise.com", "+1-555-0102", "ABC_2", "2", 3),
                (3, "Linus", "Torvalds", "ltorvalds@enterprise.com", "+1-555-0103", "ABC_3", "3", 4),
                (4, "Marie", "Curie", "mcurie@enterprise.com", "+1-555-0104", "ABC_4", "4", 6),
                (5, "Nikola", "Tesla", "ntesla@enterprise.com", "+1-555-0105", "ABC_5", "5", 7),
            ]
            cursor.executemany(
                "INSERT INTO employee (employee_id, firstname, lastname, email, mobile, sigle, employee_code, function_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                sample_employees,
            )

        conn.commit()

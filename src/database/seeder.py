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
        cursor.execute("SELECT id FROM project")
        existing_pids = {row[0] for row in cursor.fetchall()}

        sample_projects = [
            (
                1,
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
                2,
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
                3,
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
                "INSERT INTO project (id, name, status, planned_budget, actual_budget, dynamic_attributes) VALUES (?, ?, ?, ?, ?, ?)",
                sample_projects,
            )
            cursor.execute("SELECT id FROM project")
            existing_pids = {row[0] for row in cursor.fetchall()}

        # Check Tasks / Milestones
        cursor.execute("SELECT COUNT(*) FROM project_task")
        milestone_count = cursor.fetchone()[0]

        if milestone_count == 0:
            logger.info("Seeding sample project steps and tasks...")
            if 1 in existing_pids or "PRJ-001" in existing_pids:
                p1_id = 1 if 1 in existing_pids else "PRJ-001"
                cursor.execute(
                    "INSERT INTO project_task (id, project_id, task_name, phase, start_date, end_date, progress_pct, predecessor_id) VALUES (1, ?, 'Architecture & Scoping', 'Phase 1 - Inception', '2026-01-10', '2026-02-15', 100, NULL)",
                    (p1_id,),
                )
                cursor.execute(
                    "INSERT INTO project_task (id, project_id, task_name, phase, start_date, end_date, progress_pct, predecessor_id) VALUES (2, ?, 'Architecture Sign-Off', 'Phase 1 - Inception', '2026-02-15', '2026-02-15', 100, 1)",
                    (p1_id,),
                )
                cursor.execute(
                    "INSERT INTO project_task (id, project_id, task_name, phase, start_date, end_date, progress_pct, predecessor_id) VALUES (3, ?, 'Core Microservices Dev', 'Phase 2 - Build', '2026-02-16', '2026-06-30', 75, 2)",
                    (p1_id,),
                )
                cursor.execute(
                    "INSERT INTO project_task (id, project_id, task_name, phase, start_date, end_date, progress_pct, predecessor_id) VALUES (4, ?, 'Integration & UAT', 'Phase 3 - Validation', '2026-07-01', '2026-09-15', 25, 3)",
                    (p1_id,),
                )
                cursor.execute(
                    "INSERT INTO project_task (id, project_id, task_name, phase, start_date, end_date, progress_pct, predecessor_id) VALUES (5, ?, 'Go-Live Release', 'Phase 4 - Rollout', '2026-09-15', '2026-09-15', 0, 4)",
                    (p1_id,),
                )

            if 2 in existing_pids or "PRJ-002" in existing_pids:
                p2_id = 2 if 2 in existing_pids else "PRJ-002"
                cursor.execute(
                    "INSERT INTO project_task (project_id, task_name, phase, start_date, end_date, progress_pct, predecessor_id) VALUES (?, 'Data Pipeline Ingestion', 'Phase 1 - Data Eng', '2026-02-01', '2026-04-15', 100, NULL)",
                    (p2_id,),
                )
                cursor.execute(
                    "INSERT INTO project_task (project_id, task_name, phase, start_date, end_date, progress_pct, predecessor_id) VALUES (?, 'Model Training & Tuning', 'Phase 2 - ML Dev', '2026-04-16', '2026-07-30', 65, NULL)",
                    (p2_id,),
                )

            if 3 in existing_pids or "PRJ-003" in existing_pids:
                p3_id = 3 if 3 in existing_pids else "PRJ-003"
                cursor.execute(
                    "INSERT INTO project_task (project_id, task_name, phase, start_date, end_date, progress_pct, predecessor_id) VALUES (?, 'Audit Execution', 'Phase 1 - Audit', '2026-02-11', '2026-04-20', 100, NULL)",
                    (p3_id,),
                )

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
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (1, 'Directeur Général', 1, 1, NULL, NULL, 100, 1)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (2, 'Directeur Ressort 1', 2, 2, 1, NULL, 100, 1)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (3, 'Directeur Ressort 2', 2, 2, 1, NULL, 100, 1)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (4, 'Chef de Service QSE', 2, 3, 1, NULL, 100, 1)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (5, 'Chef de Service A', 3, 3, 2, NULL, 100, 1)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (6, 'Chef de Service B', 3, 3, 2, NULL, 100, 1)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (7, 'Chef de Service C', 3, 3, 2, NULL, 100, 1)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (8, 'Chef de Service D', 3, 3, 2, NULL, 100, 1)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (9, 'Chef de Service E', 3, 3, 2, NULL, 100, 1)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (10, 'Chef de Division A_1', 4, 4, 5, NULL, 100, 1)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (11, 'Chef de Division A_2', 4, 4, 5, NULL, 100, 1)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (12, 'Chef de Division A_3', 4, 4, 5, NULL, 100, 1)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (13, 'Chef de Division A_4', 4, 4, 5, NULL, 100, 1)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (14, 'Chef de Division B_1', 4, 4, 6, NULL, 100, 1)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (15, 'Chef de Division B_2', 4, 4, 6, NULL, 100, 1)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (16, 'Chef de Division B_3', 4, 4, 6, NULL, 100, 1)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (17, 'Chef de Projet A_1_A', 5, 5, 10, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (18, 'Chef de Projet A_1_B', 5, 5, 10, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (19, 'Chef de Projet A_1_C', 5, 5, 10, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (20, 'Chef de Projet A_1_D', 5, 5, 10, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (21, 'Chef de Projet A_1_E', 5, 5, 10, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (22, 'Chef de Projet A_2_F', 5, 5, 11, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (23, 'Chef de Projet A_2_G', 5, 5, 11, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (24, 'Chef de Projet A_2_H', 5, 5, 11, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (25, 'Chef de Projet A_2_J', 5, 5, 11, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (26, 'Chef de Projet A_2_K', 5, 5, 11, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (27, 'Chargé de Projet A_1_A1', 5, 6, 10, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (28, 'Chargé de Projet A_1_A2', 5, 6, 10, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (29, 'Chargé de Projet A_1_B1', 5, 6, 10, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (30, 'Chargé de Projet A_1_B2', 5, 6, 10, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (31, 'Chargé de Projet A_1_C', 5, 6, 10, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (32, 'Chargé de Projet A_1_D', 5, 6, 10, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (33, 'Chargé de Projet A_1_E', 5, 6, 10, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (34, 'Chargé de Projet A_2_F', 5, 6, 11, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (35, 'Chargé de Projet A_2_G', 5, 6, 11, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (36, 'Chargé de Projet A_2_H', 5, 6, 11, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (37, 'Chargé de Projet A_2_J', 5, 6, 11, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (38, 'Chargé de Projet A_2_K', 5, 6, 11, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (39, 'Chargé de Projet A_2_F', 5, 6, 11, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (40, 'Chargé de Projet A_2_G', 5, 6, 11, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (41, 'Chargé de Projet A_2_H', 5, 6, 11, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (42, 'Chargé de Projet A_2_J', 5, 6, 11, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (43, 'Chargé de Projet A_2_K', 5, 6, 11, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (44, 'Ingénieur B_1_1', 5, 9, 14, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (45, 'Ingénieur B_1_2', 5, 9, 14, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (46, 'Ingénieur B_2_1', 5, 9, 15, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (47, 'Assistant A_1_A', 5, 6, 10, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (48, 'Assistant A_1_B', 5, 6, 10, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (49, 'BIM Manager', 5, 8, 13, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (50, 'BIM Assistant', 5, 7, 13, NULL, 100, 0)")
          

        # Check Teams
        cursor.execute("SELECT COUNT(*) FROM team")
        team_count = cursor.fetchone()[0]
        if team_count == 0:
            logger.info("Seeding default teams...")
            sample_teams = [
                (1, "Equipe Projets A", 10, 17),
                (2, "Equipe Projets B", 10, 23),
                (3, "Equipe BIM ", 13, None),
            ]
            cursor.executemany(
                "INSERT INTO team (team_id, team_name, manager_function_id, leader_function_id) VALUES (?, ?, ?, ?)",
                sample_teams,
            )

        # Check Employees
        cursor.execute("SELECT COUNT(*) FROM employee")
        emp_count = cursor.fetchone()[0]
        if emp_count == 0:
            logger.info("Seeding default employees...")
            sample_employees = [
                (1, "Alan", "Turing", "aturing@enterprise.com", "+352 621 100 001", "ATU", "1", 1),
                (2, "Louis", "Pasteur", "lpasteur@enterprise.com", "+352 621 100 002", "LPA", "2", 2),
                (3, "Henri", "Poincaré", "hpoincare@enterprise.com", "+352 621 100 003", "HPO", "3", 3),
                (4, "Linus", "Torvalds", "ltorvalds@enterprise.com", "+352 621 100 004", "LTO", "4", 4),
                (5, "Marie", "Curie", "mcurie@enterprise.com", "+352 621 100 005", "MCU", "5", 5),
                (6, "Nikola", "Tesla", "ntesla@enterprise.com", "+352 621 100 006", "NTE", "6", 6),
                (7, "Ada", "Lovelace", "alovelace@enterprise.com", "+352 621 100 007", "ALO", "7", 7),
                (8, "Albert", "Einstein", "aeinstein@enterprise.com", "+352 621 100 008", "AEI", "8", 8),
                (9, "Grace", "Hopper", "ghopper@enterprise.com", "+352 621 100 009", "GHO", "9", 9),
                (10, "Claude", "Shannon", "cshannon@enterprise.com", "+352 621 100 010", "CSH", "10", 10),
                (11, "Dennis", "Ritchie", "dritchie@enterprise.com", "+352 621 100 011", "DRI", "11", 11),
                (12, "Ken", "Thompson", "kthompson@enterprise.com", "+352 621 100 012", "KTH", "12", 12),
                (13, "Tim", "Berners-Lee", "tbernerslee@enterprise.com", "+352 621 100 013", "TBL", "13", 13),
                (14, "Donald", "Knuth", "dknuth@enterprise.com", "+352 621 100 014", "DKN", "14", 14),
                (15, "Richard", "Feynman", "rfeynman@enterprise.com", "+352 621 100 015", "RFE", "15", 15),
                (16, "Niels", "Bohr", "nbohr@enterprise.com", "+352 621 100 016", "NBO", "16", 16),
                (17, "Margaret", "Hamilton", "mhamilton@enterprise.com", "+352 621 100 017", "MHA", "17", 17),
                (18, "John", "von Neumann", "jvonneumann@enterprise.com", "+352 621 100 018", "JVN", "18", 18),
                (19, "Steve", "Wozniak", "swozniak@enterprise.com", "+352 621 100 019", "SWO", "19", 19),
                (20, "Edsger", "Dijkstra", "edijkstra@enterprise.com", "+352 621 100 020", "EDI", "20", 20),
                (21, "Barbara", "Liskov", "bliskov@enterprise.com", "+352 621 100 021", "BLI", "21", 21),
                (22, "James", "Gosling", "jgosling@enterprise.com", "+352 621 100 022", "JGO", "22", 22),
                (23, "Guido", "van Rossum", "gvanrossum@enterprise.com", "+352 621 100 023", "GVR", "23", 23),
                (24, "Bjarne", "Stroustrup", "bstroustrup@enterprise.com", "+352 621 100 024", "BST", "24", 24),
                (25, "Vint", "Cerf", "vcerf@enterprise.com", "+352 621 100 025", "VCE", "25", 25),
                (26, "Werner", "Heisenberg", "wheisenberg@enterprise.com", "+352 621 100 026", "WHE", "26", 26),
                (27, "Max", "Planck", "mplanck@enterprise.com", "+352 621 100 027", "MPL", "27", 27),
                (28, "Erwin", "Schrödinger", "eschrodinger@enterprise.com", "+352 621 100 028", "ESC", "28", 28),
                (29, "Paul", "Dirac", "pdirac@enterprise.com", "+352 621 100 029", "PDI", "29", 29),
                (30, "Enrico", "Fermi", "efermi@enterprise.com", "+352 621 100 030", "EFE", "30", 30),
                (31, "Katherine", "Johnson", "kjohnson@enterprise.com", "+352 621 100 031", "KJO", "31", 31),
                (32, "Dorothy", "Vaughan", "dvaughan@enterprise.com", "+352 621 100 032", "DVA", "32", 32),
                (33, "Mary", "Jackson", "mjackson@enterprise.com", "+352 621 100 033", "MJA", "33", 33),
                (34, "Hedy", "Lamarr", "hlamarr@enterprise.com", "+352 621 100 034", "HLA", "34", 34),
                (35, "Radia", "Perlman", "rperlman@enterprise.com", "+352 621 100 035", "RPE", "35", 35),
                (36, "Leslie", "Lamport", "llamport@enterprise.com", "+352 621 100 036", "LLA", "36", 36),
                (37, "Andrew", "Tanenbaum", "atanenbaum@enterprise.com", "+352 621 100 037", "ATA", "37", 37),
                (38, "Brian", "Kernighan", "bkernighan@enterprise.com", "+352 621 100 038", "BKE", "38", 38),
                (39, "Robert", "Noyce", "rnoyce@enterprise.com", "+352 621 100 039", "RNO", "39", 39),
                (40, "Gordon", "Moore", "gmoore@enterprise.com", "+352 621 100 040", "GMO", "40", 40),
                (41, "John", "McCarthy", "jmccarthy@enterprise.com", "+352 621 100 041", "JMC", "41", 41),
                (42, "Marvin", "Minsky", "mminsky@enterprise.com", "+352 621 100 042", "MMI", "42", 42),
                (43, "Seymour", "Cray", "scray@enterprise.com", "+352 621 100 043", "SCR", "43", 43),
                (44, "Charles", "Babbage", "cbabbage@enterprise.com", "+352 621 100 044", "CBA", "44", 44),
                (45, "Stephen", "Hawking", "shawking@enterprise.com", "+352 621 100 045", "SHA", "45", 45),
                (46, "Carl", "Sagan", "csagan@enterprise.com", "+352 621 100 046", "CSA", "46", 46),
                (47, "Rosalind", "Franklin", "rfranklin@enterprise.com", "+352 621 100 047", "RFR", "47", 47),
                (48, "Lise", "Meitner", "lmeitner@enterprise.com", "+352 621 100 048", "LME", "48", 48),
                (49, "Alexander", "Fleming", "afleming@enterprise.com", "+352 621 100 049", "AFL", "49", 49),
                (50, "Robert", "Koch", "rkoch@enterprise.com", "+352 621 100 050", "RKO", "50", 50),
            ]
            cursor.executemany(
                "INSERT INTO employee (employee_id, firstname, lastname, email, mobile, sigle, employee_code, function_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                sample_employees,
            )

        # Check and ensure project_tag and Task_Tag groups exist
        cursor.execute("SELECT id, tag_group_name FROM tag_group")
        existing_groups = {row[1].lower().replace("_", "").replace(" ", ""): row[0] for row in cursor.fetchall()}

        if "projecttag" not in existing_groups and "projecttags" not in existing_groups:
            logger.info("Seeding project_tag group and sample project dictionary tags...")
            cursor.execute("INSERT INTO tag_group (tag_group_name) VALUES ('project_tag')")
            pt_gid = cursor.lastrowid
            cursor.executemany(
                "INSERT INTO tag_dictionnary (tag, tag_group_id) VALUES (?, ?)",
                [
                    ("Mission Critical", pt_gid),
                    ("Regulatory Compliance", pt_gid),
                    ("Strategic Initiative", pt_gid),
                    ("Pilot Project", pt_gid),
                ],
            )

        if "tasktag" not in existing_groups and "tasktags" not in existing_groups:
            logger.info("Seeding Task_Tag group and sample task dictionary tags...")
            cursor.execute("INSERT INTO tag_group (tag_group_name) VALUES ('Task_Tag')")
            tt_gid = cursor.lastrowid
            cursor.executemany(
                "INSERT INTO tag_dictionnary (tag, tag_group_id) VALUES (?, ?)",
                [
                    ("Milestone Event", tt_gid),
                    ("Critical Path", tt_gid),
                    ("Security Review", tt_gid),
                    ("High Complexity", tt_gid),
                    ("External Dependency", tt_gid),
                ],
            )

        conn.commit()

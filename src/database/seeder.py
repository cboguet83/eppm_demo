"""Default demo data seeder for PPM Studio Pro."""

import json
from typing import Optional

from src.config import config
from src.database.connection import get_db
from src.database.schema_init import init_db
from src.logging_config import get_logger
from src.models.constants import (
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
)

logger = get_logger(__name__)

DEFAULT_SCHEMA_GROUPS: list[tuple[int, str, int]] = [
    (1, "basic info", 1),
    (2, "scoping", 2),
    (3, "localization", 3),
    (4, "useful links", 4),
    (5, "classification", 5),
]

DEFAULT_SCHEMA_PARAMETERS: list[tuple[str, int, str, str, bool, str]] = [
    # (param_id, group_id, param_name, param_type, mandatory, alias)
    # basic info
    ("PRM_001", 1, "code courrier", "TEXT", False, "Code Courrier"),
    ("PRM_002", 1, "description", "TEXT", False, "Description"),
    ("PRM_003", 1, "commentaire", "TEXT", False, "Commentaire"),
    ("PRM_004", 1, "start_date", "DATE", False, "Start Date"),
    ("PRM_005", 1, "stop_Date", "DATE", False, "Stop Date"),
    ("PRM_006", 1, "lot", "TEXT", False, "Lot"),
    ("PRM_008", 1, "phase", "ENUM", False, "Phase"),
    # scoping
    ("PRM_009", 2, "benefits", "TEXT", False, "Benefits"),
    ("PRM_010", 2, "acceptance_ctriteria", "TEXT", False, "Acceptance Criteria"),
    ("PRM_011", 2, "scope", "TEXT", False, "Scope"),
    ("PRM_012", 2, "out_of_scope", "TEXT", False, "Out of Scope"),
    ("PRM_013", 2, "risks", "TEXT", False, "Risks"),
    ("PRM_014", 2, "stakeholders", "TEXT", False, "Stakeholders"),
    ("PRM_015", 2, "interfaces", "TEXT", False, "Interfaces"),
    # localization
    ("PRM_016", 3, "code_station", "ENUM", False, "Code Station"),
    ("PRM_017", 3, "code_line", "ENUM", False, "code ligne"),
    ("PRM_018", 3, "lat", "NUMBER", False, "Latitude"),
    ("PRM_019", 3, "long", "NUMBER", False, "Longitude"),
    ("PRM_020", 3, "section", "TEXT", False, "Section"),
    ("PRM_021", 3, "station", "TEXT", False, "Station"),
    ("PRM_022", 3, "pk_start", "TEXT", False, "PK Start"),
    ("PRM_023", 3, "pk_stop", "TEXT", False, "PK Stop"),
    # useful links
    ("PRM_024", 4, "acc_link", "HYPERLINK", False, "ACC Link"),
    ("PRM_025", 4, "pb_link", "HYPERLINK", False, "PB Link"),
    ("PRM_026", 4, "orga_link", "HYPERLINK", False, "Organization Link"),
    # classification
    ("PRM_027", 5, "strategic_priority", "ENUM", False, "Strategic Priority"),
    ("PRM_028", 5, "category", "ENUM", False, "Category"),
    ("PRM_029", 5, "category_tags", "TAGS", False, "Category Tags"),
    ("PRM_030", 5, "complexity", "ENUM", False, "Complexity"),
]

DEFAULT_STATUS_OPTIONS: list[str] = ["draft", "active", "completed", "canceled"]
DEFAULT_PHASE_OPTIONS: list[str] = ["FAI", "APS", "APD1", "APD2", "EXE", "CHA", "DEF", "N/A"]
DEFAULT_LINE_OPTIONS: list[str] = [
    "1", "1a", "1b", "2b", "3", "4", "5", "6", "6a", "6b", "6c", "6d", "6e", "6f", "6g", "6h", "6j", "6k", "7"
]
DEFAULT_COMPLEXITY_OPTIONS: list[str] = ["High", "Medium", "Low"]
DEFAULT_CATEGORY_OPTIONS: list[str] = ["categ1", "categ2", "categ3"]
DEFAULT_CATEGORY_TAGS: list[str] = [
    "categ1", "categ2", "categ3", "Core", "Strategic", "Cloud Native", "Infrastructure", "Modernization", "Compliance", "Digital"
]
DEFAULT_STRATEGIC_PRIORITY_OPTIONS: list[str] = ["Critical", "High", "Medium", "Low"]

DEFAULT_STATION_OPTIONS: list[str] = [
    "Alzingen Al",
    "Audun-le-Tiche Au",
    "Bascharage secteur Sanem Ba",
    "Bascharage secteur Nord Ba-N",
    "Bellain Bl",
    "Bellain-Poste de Block BI-Pb",
    "Belval B",
    "Belval-Usines Bu",
    "Belval-Lycée BLy",
    "Belval-Rédange Br",
    "Belval-Université BUn",
    "Belvaux-Soleuvre Bs",
    "Berchem Bc",
    "Berchem Est Bc-E",
    "Berchem Nord Bc-N",
    "Berchem Ouest Bc-O",
    "Berchem Sud Bc-S",
    "Bertrange-Strassen Btr",
    "Bettembourg Bt",
    "Bettembourg-Voyageurs Bt-V",
    "Bettembourg-Marchandises Bt-M",
    "Bettembourg sect. Container Terminal Bt-C",
    "Bettembourg secteur Daerenbusch Bt-D",
    "Bettembourg secteur Ouest Bt-W",
    "Bettembourg-frontière Bt-frf",
    "Betzdorf Bz",
    "Betzdorf-Poste de Block Bz-Pb",
    "Bissen Bi",
    "Biwer Bw",
    "Brucherberg Bb",
    "Burden Bd",
    "Capellen Cp",
    "Cents-Hamm Cs",
    "Cinqfontaines Cf",
    "Clervaux Cv",
    "Colmar-Berg Cb",
    "Colmar-Usines Cu",
    "Cruchten Ct",
    "Cruchten-Poste de Transition Ct-Tra",
    "Diekirch Dk",
    "Differdange (gare) D",
    "Differdange (PA) Di",
    "Dippach secteur Nord Dr-N",
    "Dippach secteur Reckange Dr",
    "Dommeldange Dm",
    "Drauffelt Df",
    "Dudelange-Usines Du",
    "Dudelange-Usines secteur Volmerange-les-Mines Vm",
    "Dudelange-Burange Db",
    "Dudelange-Centre Dc",
    "Dudelange-Ville Dv",
    "Esch-sur-Alzette Es",
    "Esch-sur-Alzette-frontière Es-frt",
    "Esch secteur Lallange Es-L",
    "Esch secteur Usines Es-Us",
    "Ettelbruck Eb",
    "Fentange F",
    "Fentange sud (Ligne 4) F-S4",
    "Fentange sud (Ligne 6) F-S6",
    "Fléibour Fb",
    "Goebelsmuhle Gb",
    "Hagelsdorf Hgd",
    "Heisdorf Hd",
    "Howald Ho",
    "Huncherange Hu",
    "Kautenbach Kt",
    "Kayl Ka",
    "Kleinbettingen Kb",
    "Kleinbettingen-frontière Kb-frb",
    "Kockelscheuer-Poste de block Ko-Pb",
    "Lamadelaine Lm",
    "Langengrund Lg",
    "Leudelange Ld",
    "Lintgen Li",
    "Livange Liv",
    "Lorentzweiler Lr",
    "Luxembourg L",
    "Luxembourg gare centrale Lgc",
    "Luxembourg sect Cents-Hamm L-Cs",
    "Luxembourg sect Stadtgrund Ligne 1 L-St",
    "Luxembourg sect Stadtgrund Ligne 3 L-St3",
    "Luxembourg secteur Gasperich Ga",
    "Luxembourg secteur Hollerich Lh",
    "Luxembourg secteur Triage Lt",
    "Luxembourg-L-Cm  secteur Centre de maintenance",
    "Luxembourg - secteur Centre de remisage L-Crm",
    "Mamer Mr",
    "Mamer-Lycée Mr-L",
    "Manternach Mn",
    "Manternach-Poste de Block Mn-Pb",
    "Mecher Me",
    "Merkholtz Mk",
    "Merkholtz-Poste de Block Mk-Pb",
    "Mersch M",
    "Mertert Mt",
    "Mertert-Port Mt-P",
    "Mertert-Klinker Mt-K",
    "Michelau Mc",
    "Munsbach Mb",
    "Munsbach-Poste de Block Mb-Pb",
    "Niederkorn Nk",
    "Noertzange Nz",
    "Oberkorn Ok",
    "Oetrange Oe",
    "Paradiso Pa",
    "Pétange P",
    "Pétange secteur Rodange R",
    "Pfaffenthal - Kirchberg Pf-K",
    "Rodange-frontière française R-frf",
    "Rodange-frontière Aub R-frb1",
    "Rodange-frontière A R-frb2",
    "Réseau tertiaire - site de Belval RT-Bu",
    "Réseau tertiaire - site de Differdange RT-D",
    "Réseau tertiaire – site de Rodange RT-R",
    "Réseau tertiaire – site de Schifflange RT-Sg",
    "Roodt Rt",
    "Roodt Poste de Transition Rt-Tra",
    "Rumelange Ru",
    "Sandweiler-Contern Sc",
    "Scheuerbusch Schb",
    "Schieren – Ligne 1 Sr",
    "Schieren – Ligne 2 Sr2",
    "Schifflange Sg",
    "Schouweiler Sw",
    "Scheidhof Sh",
    "Syren Sy",
    "Tétange Tg",
    "Troisvierges Tv",
    "Troisvierges secteur Pfaffenmuhle Tv-P",
    "Troisvierges-frontière Tv-frb",
    "Walferdange Wf",
    "Wasserbillig W",
    "Wasserbillig-frontière W-frd",
    "Wecker Wk",
    "Wiltz Wz",
    "Wilwerwiltz Ww",
    "Athus: A",
    "Arlon: Ar",
    "Aubange-Bifurcation: Aub",
    "Autelbas: Aut",
    "Gouvy: Gy",
    "Hettange-Grande: Hg",
    "Igel: Ig",
    "Longwy: Lw",
    "Mont St Martin-Bifurcation: MSM",
    "Thionville: Thl",
    "Trier Hbf: Tr",
]

DEFAULT_PARAM_OPTIONS: dict[str, list[str]] = {
    "PRM_008": DEFAULT_PHASE_OPTIONS,
    "PRM_016": DEFAULT_STATION_OPTIONS,
    "PRM_017": DEFAULT_LINE_OPTIONS,
    "PRM_027": DEFAULT_STRATEGIC_PRIORITY_OPTIONS,
    "PRM_028": DEFAULT_CATEGORY_OPTIONS,
    "PRM_029": DEFAULT_CATEGORY_TAGS,
    "PRM_030": DEFAULT_COMPLEXITY_OPTIONS,
}


def seed_default_data_if_empty(db_path: Optional[str] = None, force: bool = False) -> None:
    """Populates the database with demo schema, projects, and milestones.

    Args:
        db_path: Filepath to the SQLite database. If None, uses default from config.
        force: If True, flushes all existing data before seeding. Default False.
    """
    target_path = db_path if db_path is not None else config.db_path
    logger.info("Checking if database seeding is required for %s (force=%s)", target_path, force)

    init_db(target_path)


    with get_db(target_path) as conn:
        cursor = conn.cursor()

        if force:
            logger.info("Forcing database reseed: wiping existing data from all tables...")
            conn.execute("PRAGMA foreign_keys = OFF")
            tables_to_flush = [
                "resource_pool_assignment",
                "resource_pool_mapping",
                "resource_pool",
                "team_function",
                "task_tag",
                "project_tag",
                "task_dependencies",
                "project_task",
                "project",
                "employee_calendar_exception",
                "employee",
                "team",
                "function",
                "function_type",
                "tag_dictionnary",
                "tag_group",
                "schema_param_options",
                "schema_parameters",
                "schema_groups",
            ]
            for table in tables_to_flush:
                cursor.execute(f"DELETE FROM {table}")
            cursor.execute(
                "DELETE FROM sqlite_sequence WHERE name IN ("
                + ", ".join(f"'{t}'" for t in tables_to_flush)
                + ")"
            )
            conn.commit()
            conn.execute("PRAGMA foreign_keys = ON")

        # Check Schema Groups
        cursor.execute("SELECT COUNT(*) FROM schema_groups")
        group_count = cursor.fetchone()[0]


        if group_count == 0:
            logger.info("Seeding default schema groups, parameters, and enum options...")
            cursor.executemany(
                "INSERT OR IGNORE INTO schema_groups (id, group_name, display_order) VALUES (?, ?, ?)",
                DEFAULT_SCHEMA_GROUPS,
            )

            for p_id, g_id, p_name, p_type, mand, alias in DEFAULT_SCHEMA_PARAMETERS:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO schema_parameters (param_id, group_id, param_name, param_type, mandatory, alias)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (p_id, g_id, p_name, p_type, 1 if mand else 0, alias),
                )

            for param_id, opts in DEFAULT_PARAM_OPTIONS.items():
                for idx, opt in enumerate(opts, 1):
                    cursor.execute(
                        "INSERT INTO schema_param_options (param_id, option_value, display_order) VALUES (?, ?, ?)",
                        (param_id, opt, idx),
                    )

        # Clean up legacy status parameter from dynamic schema if present
        cursor.execute("DELETE FROM schema_parameters WHERE param_name = 'status'")
        cursor.execute("DELETE FROM schema_param_options WHERE param_id = 'PRM_007'")

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
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (51, 'Chef de Division C_1', 4, 4, 7, NULL, 100, 1)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (52, 'Chef de Division C_2', 4, 4, 7, NULL, 100, 1)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (53, 'Chef de Division D_1', 4, 4, 8, NULL, 100, 1)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (54, 'Chef de Division D_2', 4, 4, 8, NULL, 100, 1)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (55, 'Chef de Division E_1', 4, 4, 9, NULL, 100, 1)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (56, 'Chef de Division E_2', 4, 4, 9, NULL, 100, 1)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (57, 'Chef de Projet B_1_A', 5, 5, 14, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (58, 'Chef de Projet C_1_A', 5, 5, 51, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (59, 'Chef de Projet D_1_A', 5, 5, 53, NULL, 100, 0)")
            cursor.execute("INSERT INTO function (function_id, name, hierarchy_level, function_type_id, manager_function_id, dual_manager_function_id, fte_percentage, has_reports) VALUES (60, 'Chef de Projet E_1_A', 5, 5, 55, NULL, 100, 0)")
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
                    "code courrier": "CR-2026-001",
                    "description": "Modernization of ERP core services across logistics and finance",
                    "commentaire": "Phase 1 architecture validated by steerco",
                    "start_date": "2026-01-10",
                    "stop_Date": "2026-12-31",
                    "lot": "Lot 1 - Core Backend",
                    "phase": "EXE",
                    "benefits": "Increases system throughput, unifies ledger, and reduces operating costs by 22%",
                    "acceptance_ctriteria": "Pass 100% UAT test scenarios and verify automated reconciliations",
                    "scope": "Inventory management, general ledger, and human capital modules",
                    "out_of_scope": "Legacy mainframe payroll archive interfaces",
                    "risks": "Database schema migration downtime during live cutover",
                    "stakeholders": "Finance Director, Operations VP, IT Steering Committee",
                    "interfaces": "Core SAP Gateway, Legacy Oracle DB, Active Directory",
                    "code_station": "Luxembourg L",
                    "code_line": "1",
                    "lat": 49.6000,
                    "long": 6.1333,
                    "section": "Section Alpha",
                    "station": "Luxembourg Gare Centrale",
                    "pk_start": "PK 0+000",
                    "pk_stop": "PK 14+500",
                    "acc_link": "https://internal.enterprise.org/acc/erp-2026",
                    "pb_link": "https://jira.enterprise.org/browse/ERP-2026",
                    "orga_link": "https://confluence.enterprise.org/pages/view/erp-modernization",
                    "strategic_priority": "Critical",
                    "category": "categ1",
                    "category_tags": ["Core", "Strategic", "Cloud Native"],
                    "complexity": "High",
                }),
                17,
            ),
            (
                2,
                "Customer 360 AI Analytics",
                STATUS_IN_PROGRESS,
                280000.0,
                310000.0,
                json.dumps({
                    "code courrier": "CR-2026-002",
                    "description": "Customer 360 AI Analytics Platform",
                    "commentaire": "Initial model training shows 94% accuracy",
                    "start_date": "2026-02-01",
                    "stop_Date": "2026-10-15",
                    "lot": "Lot 2 - ML Pipelines",
                    "phase": "APD2",
                    "benefits": "Provides real-time customer behavior predictions and churn early-warning signals",
                    "acceptance_ctriteria": "Real-time stream latency < 500ms and model precision > 90%",
                    "scope": "Omnichannel behavioral ingestion and marketing segmentation pipelines",
                    "out_of_scope": "Third-party ad-network direct bidding integration",
                    "risks": "Data privacy and GDPR consent compliance overhead",
                    "stakeholders": "Chief Marketing Officer, Data Science Lead, Compliance Officer",
                    "interfaces": "Apache Kafka, Snowflake Lakehouse, CRM API",
                    "code_station": "Bettembourg Bt",
                    "code_line": "6",
                    "lat": 49.5186,
                    "long": 6.0986,
                    "section": "Section Sud 6",
                    "station": "Bettembourg Voyageurs",
                    "pk_start": "PK 5+200",
                    "pk_stop": "PK 18+750",
                    "acc_link": "https://internal.enterprise.org/acc/c360-ai",
                    "pb_link": "https://jira.enterprise.org/browse/C360-AI",
                    "orga_link": "https://confluence.enterprise.org/pages/view/customer-360",
                    "strategic_priority": "High",
                    "category": "categ2",
                    "category_tags": ["AI/ML", "Analytics", "Innovation"],
                    "complexity": "Medium",
                }),
                18,
            ),
            (
                3,
                "Global Supply Chain Audit",
                STATUS_COMPLETED,
                150000.0,
                142000.0,
                json.dumps({
                    "code courrier": "CR-2026-003",
                    "description": "Global Supply Chain Compliance & Audit",
                    "commentaire": "All audit recommendations remediated and approved",
                    "start_date": "2026-02-11",
                    "stop_Date": "2026-08-30",
                    "lot": "Lot 3 - Governance Audit",
                    "phase": "DEF",
                    "benefits": "Ensures full ISO-27001 and regulatory supply chain compliance",
                    "acceptance_ctriteria": "Zero high or critical findings on external audit sign-off",
                    "scope": "Global logistics vendors, supply warehousing, and customs clearance procedures",
                    "out_of_scope": "Direct tier-3 raw material suppliers",
                    "risks": "Vendor documentation delivery delays",
                    "stakeholders": "Audit Committee, Chief Legal Counsel, Procurement Director",
                    "interfaces": "ERP Vendor Portal, Customs Electronic Clearinghouse",
                    "code_station": "Esch-sur-Alzette Es",
                    "code_line": "6a",
                    "lat": 49.4958,
                    "long": 5.9806,
                    "section": "Section Ouest 6a",
                    "station": "Esch-sur-Alzette",
                    "pk_start": "PK 1+100",
                    "pk_stop": "PK 8+900",
                    "acc_link": "https://internal.enterprise.org/acc/audit-2026",
                    "pb_link": "https://jira.enterprise.org/browse/AUD-2026",
                    "orga_link": "https://confluence.enterprise.org/pages/view/supply-audit",
                    "strategic_priority": "Medium",
                    "category": "categ3",
                    "category_tags": ["Compliance", "Operations"],
                    "complexity": "Low",
                }),
                22,
            ),
        ]

        if not existing_pids:
            logger.info("Seeding sample projects...")
            cursor.executemany(
                "INSERT INTO project (id, name, status, planned_budget, actual_budget, dynamic_attributes, function_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
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
                (1, "Linus", "Torvalds", "ltorvalds@enterprise.com", "+352 621 100 004", "LTO", "1", 1),
                (2, "Louis", "Pasteur", "lpasteur@enterprise.com", "+352 621 100 002", "LPA", "2", 2),
                (3, "Henri", "Poincaré", "hpoincare@enterprise.com", "+352 621 100 003", "HPO", "3", 3),
                (4, "Alan", "Turing", "aturing@enterprise.com", "+352 621 100 001", "ATU", "4", 4),
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

        # Check and seed Team Functions
        cursor.execute("SELECT COUNT(*) FROM team_function")
        tf_count = cursor.fetchone()[0]
        if tf_count == 0:
            logger.info("Seeding team member functions...")
            team_func_samples = [
                # Team 1: Equipe Projets A
                (1, 10), (1, 17), (1, 18), (1, 19), (1, 20), (1, 21),
                (1, 27), (1, 28), (1, 29), (1, 30), (1, 31), (1, 32), (1, 33), (1, 47), (1, 48),
                # Team 2: Equipe Projets B
                (2, 11), (2, 22), (2, 23), (2, 24), (2, 25), (2, 26),
                (2, 34), (2, 35), (2, 36), (2, 37), (2, 38), (2, 44), (2, 45),
                # Team 3: Equipe BIM
                (3, 13), (3, 49), (3, 50),
            ]
            cursor.execute("SELECT function_id FROM function")
            valid_func_ids = {r[0] for r in cursor.fetchall()}
            cursor.execute("SELECT team_id FROM team")
            valid_team_ids = {r[0] for r in cursor.fetchall()}
            valid_team_funcs = [
                (t, f) for (t, f) in team_func_samples if t in valid_team_ids and f in valid_func_ids
            ]
            if valid_team_funcs:
                cursor.executemany(
                    "INSERT OR IGNORE INTO team_function (team_id, function_id) VALUES (?, ?)",
                    valid_team_funcs,
                )

        # Check and seed Resource Pools
        cursor.execute("SELECT COUNT(*) FROM resource_pool")
        pool_count = cursor.fetchone()[0]
        if pool_count == 0:
            logger.info("Seeding default resource pools, mappings, and assignments...")
            sample_pools = [
                (1, "Core Engineering Pool", "Central pool combining Project Team A and BIM specialists."),
                (2, "BIM Specialist Pool", "Dedicated BIM modeling and coordination unit."),
                (3, "Technical Architecture Pool", "Senior engineering & cloud native systems architecture."),
            ]
            cursor.executemany(
                "INSERT INTO resource_pool (id, name, description) VALUES (?, ?, ?)",
                sample_pools,
            )

            # Seed Mappings (with de-duplication demonstration: Function 17 mapped via Team 1 AND directly)
            cursor.execute("SELECT function_id FROM function")
            valid_func_ids = {r[0] for r in cursor.fetchall()}
            cursor.execute("SELECT team_id FROM team")
            valid_team_ids = {r[0] for r in cursor.fetchall()}

            sample_mappings = [
                # Pool 1
                (1, "team", 1, 100.0),       # Team 1 at 100%
                (1, "function", 17, 100.0),   # Function 17 directly (already in Team 1 -> must be deduplicated!)
                (1, "function", 49, 50.0),    # Function 49 (BIM Manager) directly at 50%
                # Pool 2
                (2, "team", 3, 100.0),       # Team 3 (Equipe BIM) at 100%
                # Pool 3
                (3, "function", 44, 100.0),   # Ingénieur B_1_1 at 100%
                (3, "function", 45, 75.0),    # Ingénieur B_1_2 at 75%
                (3, "function", 46, 50.0),    # Ingénieur B_2_1 at 50%
            ]
            valid_mappings = [
                m for m in sample_mappings
                if (m[1] == "team" and m[2] in valid_team_ids) or (m[1] == "function" and m[2] in valid_func_ids)
            ]
            if valid_mappings:
                cursor.executemany(
                    "INSERT INTO resource_pool_mapping (pool_id, target_type, target_id, allocation_pct) VALUES (?, ?, ?, ?)",
                    valid_mappings,
                )

            # Seed Sample Assignments using valid existing projects and tasks
            cursor.execute("SELECT id, project_id FROM project_task ORDER BY id LIMIT 3")
            existing_tasks = cursor.fetchall()
            sample_assignments = []
            if existing_tasks:
                t1_id, p1_id = existing_tasks[0]
                sample_assignments.append((1, p1_id, t1_id, 3.0, "2026-01-10", "2026-02-15", "Core system scoping & discovery"))
                if len(existing_tasks) > 1:
                    t2_id, p2_id = existing_tasks[1]
                    sample_assignments.append((1, p2_id, t2_id, 4.0, "2026-02-16", "2026-06-30", "Backend development squad"))
                if len(existing_tasks) > 2:
                    t3_id, p3_id = existing_tasks[2]
                    sample_assignments.append((2, p3_id, t3_id, 1.5, "2026-03-01", "2026-05-30", "BIM 3D telemetry ingestion"))

            cursor.execute("SELECT id FROM project ORDER BY id LIMIT 1")
            proj_row = cursor.fetchone()
            if proj_row:
                sample_assignments.append((3, proj_row[0], None, 1.0, None, None, "Portfolio advisory & oversight"))

            if sample_assignments:
                cursor.executemany(
                    "INSERT INTO resource_pool_assignment (pool_id, project_id, task_id, fte_assigned, start_date, end_date, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    sample_assignments,
                )

        conn.commit()


seed_database_data = seed_default_data_if_empty


def main() -> None:
    """CLI entrypoint for database seeder."""
    import argparse

    parser = argparse.ArgumentParser(description="Seed default EPPM database schema, taxonomy, and sample data.")
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Optional path to custom SQLite database file.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-seeding by wiping existing data first.",
    )
    args = parser.parse_args()
    seed_default_data_if_empty(db_path=args.db_path, force=args.force)
    print("Database seeding completed successfully.")


if __name__ == "__main__":
    main()

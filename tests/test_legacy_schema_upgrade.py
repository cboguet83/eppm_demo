"""Upgrade isolated legacy schemas without losing business ownership or data."""

from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from app.infrastructure.database.connection import get_db
from app.infrastructure.database.schema_init import init_db
from app.infrastructure.repositories.access import SqliteAccessGateway


@pytest.mark.parametrize("rich_tasks", [False, True])
def test_legacy_projects_and_dependencies_keep_their_owners_through_access_upgrade(
    tmp_path: Path, rich_tasks: bool,
):
    path = str(tmp_path / "legacy-planning.db")
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("""CREATE TABLE projects (
            id PRIMARY KEY, name TEXT, status TEXT, planned_budget REAL,
            actual_budget REAL, dynamic_attributes TEXT)""")
        connection.executemany(
            "INSERT INTO projects VALUES (?,?,'Draft',1200.25,150.75,'{}')",
            [(1, "Integer project"), ("2", "Text number project"),
             ("PRJ-3", "Prefixed project"), ("external", "Other project")],
        )
        connection.execute("""CREATE TABLE project_milestones (
            id INTEGER PRIMARY KEY, project_id, task_name TEXT,
            start_date TEXT, end_date TEXT)""")
        connection.executemany(
            "INSERT INTO project_milestones VALUES (?,?,?,'2026-06-01','2026-06-05')",
            [(11, 1, "First"), (12, "2", "Second"), (13, "PRJ-3", "Third")],
        )
        if rich_tasks:
            connection.execute("ALTER TABLE project_milestones ADD COLUMN phase TEXT DEFAULT 'Build'")
            connection.execute("ALTER TABLE project_milestones ADD COLUMN progress_pct INTEGER DEFAULT 25")
            connection.execute("ALTER TABLE project_milestones ADD COLUMN description TEXT DEFAULT 'Retained note'")
            connection.execute("ALTER TABLE project_milestones ADD COLUMN predecessor_id INTEGER")
            connection.execute("UPDATE project_milestones SET predecessor_id=11 WHERE id=12")
        connection.execute("""CREATE TABLE task_dependencies (
            id INTEGER PRIMARY KEY, task_id INTEGER REFERENCES project_milestones(id),
            predecessor_task_id INTEGER REFERENCES project_milestones(id),
            predecessor_project_id REFERENCES projects(id), link_type TEXT, lag_days INTEGER)""")
        connection.executemany("INSERT INTO task_dependencies VALUES (?,?,?,?,?,?)", [
            (1, 12, 11, None, "FS", 2), (2, 13, None, 1, "SS", -1),
            (3, 13, None, "2", "FF", 3), (4, 11, None, "PRJ-3", "SF", 4),
        ])

    init_db(path)

    with closing(get_db(path)) as connection:
        assert connection.execute(
            "SELECT id,name,planned_budget,actual_budget FROM project ORDER BY id"
        ).fetchall() == [
            (1, "Integer project", 1200.25, 150.75), (2, "Text number project", 1200.25, 150.75),
            (3, "Prefixed project", 1200.25, 150.75), (4, "Other project", 1200.25, 150.75),
        ]
        assert connection.execute(
            "SELECT id,project_id,task_name FROM project_task ORDER BY id"
        ).fetchall() == [(11, 1, "First"), (12, 2, "Second"), (13, 3, "Third")]
        assert connection.execute(
            "SELECT phase,progress_pct,description,predecessor_id FROM project_task WHERE id=12"
        ).fetchone() == (("Build", 25, "Retained note", 11) if rich_tasks else ("General", 0, "", None))
        dependencies = connection.execute(
            "SELECT id,task_id,predecessor_task_id,predecessor_project_id,link_type,lag_days "
            "FROM task_dependencies ORDER BY id"
        ).fetchall()
        assert dependencies == [
            (1, 12, 11, None, "FS", 2), (2, 13, None, 1, "SS", -1),
            (3, 13, None, 2, "FF", 3), (4, 11, None, 3, "SF", 4),
        ]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        versions = connection.execute("SELECT version FROM schema_migration ORDER BY version").fetchall()
        assert ("oidc-access-v1",) in versions
        assert not connection.execute(
            "SELECT name FROM sqlite_master WHERE name IN ('projects','project_milestones')"
        ).fetchall()
    with SqliteAccessGateway(path).transaction() as store:
        assert store.list_users("", 100) == []
    with closing(sqlite3.connect(path + ".before-project-types.bak")) as backup:
        assert backup.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 4
        assert backup.execute("SELECT COUNT(*) FROM project_milestones").fetchone()[0] == 3
    init_db(path)
    with closing(get_db(path)) as connection:
        assert connection.execute("SELECT version FROM schema_migration ORDER BY version").fetchall() == versions
        assert connection.execute("SELECT * FROM task_dependencies ORDER BY id").fetchall() == dependencies
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("parameter_schema,insert,expected", [
    (
        "id INTEGER PRIMARY KEY, group_id INTEGER, param_name TEXT, param_type TEXT",
        "INSERT INTO schema_parameters VALUES (7,1,'Department','ENUM')",
        ("PRM_007", "Department", "ENUM", 0, ""),
    ),
    (
        "id INTEGER PRIMARY KEY, param_id TEXT, group_id INTEGER, param_name TEXT, "
        "param_type TEXT, mandatory INTEGER, alias TEXT",
        "INSERT INTO schema_parameters VALUES (7,'DEPT',1,'Department','ENUM',1,'Dept')",
        ("DEPT", "Department", "ENUM", 1, "Dept"),
    ),
    (
        "param_id TEXT PRIMARY KEY, group_id INTEGER, param_name TEXT, param_type TEXT",
        "INSERT INTO schema_parameters VALUES ('DEPT',1,'Department','ENUM')",
        ("DEPT", "Department", "ENUM", 0, ""),
    ),
])
def test_legacy_parameter_identity_and_required_fields_survive_migration(
    tmp_path: Path, parameter_schema: str, insert: str, expected: tuple,
):
    path = str(tmp_path / "legacy-parameters.db")
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE schema_groups(id INTEGER PRIMARY KEY, group_name TEXT, display_order INTEGER)")
        connection.execute("INSERT INTO schema_groups VALUES (1,'Classification',1)")
        connection.execute("CREATE TABLE schema_parameters (" + parameter_schema + ")")
        connection.execute(insert)

    init_db(path)
    init_db(path)

    with closing(get_db(path)) as connection:
        assert connection.execute(
            "SELECT param_id,param_name,param_type,mandatory,alias FROM schema_parameters"
        ).fetchall() == [expected]
        columns = {row[1]: row for row in connection.execute("PRAGMA table_info(schema_parameters)")}
        assert columns["param_id"][5] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO schema_parameters(param_id,param_name,param_type) VALUES (?,'Duplicate','ENUM')",
                (expected[0],),
            )


@pytest.mark.parametrize("hierarchy", ["legacy_id", "foreign_key", "current"])
def test_legacy_directory_and_pool_mappings_survive_access_upgrade_without_becoming_users(tmp_path: Path, hierarchy: str):
    path = str(tmp_path / "legacy-directory.db")
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE project(id INTEGER PRIMARY KEY,name TEXT,status TEXT)")
        connection.execute("INSERT INTO project VALUES(11,'Existing project','Draft')")
        connection.execute("CREATE TABLE function_type(function_type_id INTEGER PRIMARY KEY,type_name TEXT NOT NULL UNIQUE)")
        connection.execute("INSERT INTO function_type VALUES(10,'Engineering')")
        connection.execute("CREATE TABLE hierarchy_level(id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO hierarchy_level VALUES(3)")
        level = "hierarchy_level_id" if hierarchy == "legacy_id" else "hierarchy_level"
        fields = ",function_type_id INTEGER,fte_percentage INTEGER,has_reports INTEGER" if hierarchy == "foreign_key" else ""
        foreign_key = f",FOREIGN KEY({level}) REFERENCES hierarchy_level(id)" if hierarchy == "foreign_key" else ""
        connection.execute(f"""CREATE TABLE function(
            function_id INTEGER PRIMARY KEY,name TEXT,{level} INTEGER,
            manager_function_id INTEGER,dual_manager_function_id INTEGER{fields}{foreign_key})""")
        values = ",10,75,1" if hierarchy == "foreign_key" else ""
        connection.execute(f"INSERT INTO function VALUES(10,'Delivery',3,NULL,NULL{values})")
        employee_fk = ",FOREIGN KEY(function_type_id) REFERENCES function_type(function_type_id)" if hierarchy != "current" else ""
        connection.execute(f"""CREATE TABLE employee(
            employee_id INTEGER PRIMARY KEY,firstname TEXT,lastname TEXT,email TEXT UNIQUE,
            mobile TEXT,sigle TEXT,employee_code TEXT UNIQUE,function_id INTEGER,function_type_id INTEGER,
            FOREIGN KEY(function_id) REFERENCES function(function_id){employee_fk})""")
        connection.execute("INSERT INTO employee VALUES(10,'Rae','Legacy','legacy@example.test','123','RL','LEG10',10,10)")
        connection.execute("CREATE TABLE resource_pool(id INTEGER PRIMARY KEY,name TEXT,description TEXT,created_at TEXT)")
        connection.execute("INSERT INTO resource_pool VALUES(1,'Legacy pool','Retained','2026-01-01')")
        connection.execute("""CREATE TABLE resource_pool_mapping(
            id INTEGER PRIMARY KEY,pool_id INTEGER,target_type TEXT CHECK(target_type IN ('team','function')),
            target_id INTEGER,allocation_pct REAL,FOREIGN KEY(pool_id) REFERENCES resource_pool(id))""")
        connection.execute("INSERT INTO resource_pool_mapping VALUES(1,1,'function',10,75)")
        connection.execute("""CREATE TABLE resource_pool_assignment(
            id INTEGER PRIMARY KEY,pool_id INTEGER,project_id INTEGER,task_id INTEGER,fte_assigned REAL,notes TEXT,
            FOREIGN KEY(pool_id) REFERENCES resource_pool(id),FOREIGN KEY(project_id) REFERENCES project(id))""")
        connection.execute("INSERT INTO resource_pool_assignment VALUES(1,1,11,NULL,0.5,'Existing demand')")

    init_db(path)
    init_db(path)

    with closing(get_db(path)) as connection, connection:
        assert connection.execute("SELECT function_id,name,hierarchy_level,function_type_id,fte_percentage,has_reports FROM function").fetchall() == [
            (10, "Delivery", 3, 10, 75, 1) if hierarchy == "foreign_key" else (10, "Delivery", 3, None, 100, 0),
        ]
        assert connection.execute("SELECT employee_id,email,employee_code,function_id,occupation_percentage FROM employee").fetchall() == [
            (10, "legacy@example.test", "LEG10", 10, 100),
        ]
        assert "function_type_id" not in {row[1] for row in connection.execute("PRAGMA table_info(employee)")}
        assert connection.execute("SELECT planned_budget,actual_budget FROM project WHERE id=11").fetchone() == (0, 0)
        assert connection.execute("SELECT capacity_fte FROM resource_pool WHERE id=1").fetchone() == (None,)
        assert connection.execute("SELECT id,target_type,target_id,allocation_pct FROM resource_pool_mapping").fetchall() == [(1, "function", 10, 75)]
        connection.execute("INSERT INTO resource_pool_mapping(pool_id,target_type,target_id,allocation_pct) VALUES(1,'employee',10,25)")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO resource_pool_mapping(pool_id,target_type,target_id,allocation_pct) VALUES(1,'employee',10,25)")
        assert connection.execute("SELECT project_id,fte_assigned,start_date,end_date,notes FROM resource_pool_assignment").fetchall() == [(11, 0.5, None, None, "Existing demand")]
        assert connection.execute("SELECT count(*) FROM app_user").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM app_identity").fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

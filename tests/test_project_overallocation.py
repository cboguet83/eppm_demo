"""Portfolio warnings use any-day pool overloads, not period averages."""

from contextlib import closing

from app.infrastructure.database.connection import get_db
from app.infrastructure.database.schema_init import init_db
from app.operator_services import create_project_service
from app.operator_services import create_project_overallocation_service


def test_only_positive_consumers_overlapping_an_overloaded_day_are_flagged(tmp_path):
    path = str(tmp_path / "capacity.db")
    init_db(path)
    for name in ("Year-long", "One day", "Later", "Zero demand"):
        create_project_service(path).create_project(name=name)
    with closing(get_db(path)) as conn, conn:
        conn.execute("INSERT INTO resource_pool(id,name,capacity_fte) VALUES (1,'Pool',1)")
        conn.executemany("""INSERT INTO resource_pool_assignment(pool_id,project_id,fte_assigned,start_date,end_date)
            VALUES (1,?,?,?,?)""", [(1, 1, "2027-01-01", "2027-12-31"),
                                    (2, 0.1, "2027-05-15", "2027-05-15"),
                                    (3, 1, "2028-01-01", "2028-01-01"),
                                    (4, 0, "2027-01-01", "2027-12-31")])
    assert create_project_overallocation_service(path).overallocated_project_ids([1, 2, 3, 4]) == {1, 2}
    assert create_project_overallocation_service(path).overallocated_project_ids([3, 4]) == set()
    assert create_project_overallocation_service(path).overallocated_project_ids([]) == set()
    with closing(get_db(path)) as conn, conn:
        conn.execute("UPDATE resource_pool SET capacity_fte=2 WHERE id=1")
    assert create_project_overallocation_service(path).overallocated_project_ids([1, 2, 3, 4]) == set()


def test_staffed_pool_uses_assigned_capacity_and_exception_zero_not_theory(tmp_path):
    path = str(tmp_path / "staffed.db")
    init_db(path)
    create_project_service(path).create_project(name="Assigned")
    with closing(get_db(path)) as conn, conn:
        conn.execute("INSERT INTO resource_pool(id,name,capacity_fte) VALUES (1,'Pool',10)")
        conn.execute("""INSERT INTO employee(employee_id,firstname,lastname,email,employee_code)
            VALUES (1,'A','Person','a@example.test','A')""")
        conn.execute("INSERT INTO resource_pool_mapping(pool_id,target_type,target_id) VALUES (1,'employee',1)")
        conn.execute("""INSERT INTO resource_pool_assignment(pool_id,project_id,fte_assigned,start_date,end_date)
            VALUES (1,1,0.5,'2027-01-01','2027-12-31')""")
    assert create_project_overallocation_service(path).overallocated_project_ids([1]) == set()
    with closing(get_db(path)) as conn, conn:
        conn.execute("""INSERT INTO employee_calendar_exception(employee_id,start_date,end_date,occupation_percentage)
            VALUES (1,'2027-06-10','2027-06-10',0)""")
    assert create_project_overallocation_service(path).overallocated_project_ids([1]) == {1}

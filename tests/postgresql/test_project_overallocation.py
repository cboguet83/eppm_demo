"""Portfolio warnings retain any-day overload and actual staffing semantics."""

import psycopg

from app.application.services.business_access import BusinessAccess
from app.main import create_project_overallocation_service, create_project_service
from app.runtime import RuntimeResources
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.ui import runtime as runtime, access as access


def test_only_positive_consumers_overlapping_an_overloaded_day_are_flagged(
    runtime: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture,
) -> None:
    """Long and one-day consumers are flagged only where positive demand overlaps."""
    projects = create_project_service(runtime, access=access)
    identities = [projects.create_project(name=name) for name in (
        'Year-long', 'One day', 'Later', 'Zero demand',
    )]
    with psycopg.connect(authorized.setup.operator_url) as connection, connection.cursor() as cursor:
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES (1,'Pool',1)")
        cursor.executemany(
            'INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,fte_assigned,start_date,end_date) '
            'VALUES (1,%s,%s,%s,%s)',
            [(identity, demand, start, end) for identity, (demand, start, end) in zip(identities, (
                (1, '2027-01-01', '2027-12-31'),
                (0.1, '2027-05-15', '2027-05-15'),
                (1, '2028-01-01', '2028-01-01'),
                (0, '2027-01-01', '2027-12-31'),
            ))],
        )
    service = create_project_overallocation_service(runtime, access=access)
    assert service.overallocated_project_ids(identities) == set(identities[:2])
    assert service.overallocated_project_ids(identities[2:]) == set()
    assert service.overallocated_project_ids([]) == set()
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.resource_pool SET capacity_fte=2 WHERE id=1')
    assert service.overallocated_project_ids(identities) == set()


def test_staffed_pool_uses_assigned_capacity_and_exception_zero_not_theory(
    runtime: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture,
) -> None:
    """A single calendar exception can exhaust a pool with ample theoretical capacity."""
    project = create_project_service(runtime, access=access).create_project(name='Assigned')
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.resource_pool(id,name,capacity_fte) VALUES (1,'Pool',10)")
        connection.execute("""INSERT INTO eppm.employee(employee_id,firstname,lastname,email,employee_code)
            VALUES (1,'A','Person','a@example.test','A')""")
        connection.execute("INSERT INTO eppm.resource_pool_mapping(pool_id,target_type,target_id) VALUES (1,'employee',1)")
        connection.execute("""INSERT INTO eppm.resource_pool_assignment(pool_id,project_id,fte_assigned,start_date,end_date)
            VALUES (1,%s,0.5,'2027-01-01','2027-12-31')""", (project,))
    service = create_project_overallocation_service(runtime, access=access)
    assert service.overallocated_project_ids([project]) == set()
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""INSERT INTO eppm.employee_calendar_exception(employee_id,start_date,end_date,occupation_percentage)
            VALUES (1,'2027-06-10','2027-06-10',0)""")
    assert service.overallocated_project_ids([project]) == {project}

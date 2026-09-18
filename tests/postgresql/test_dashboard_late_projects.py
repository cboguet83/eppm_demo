"""Late-project metrics use filtered projects and only their current plan tasks."""

from datetime import date

import psycopg

from tests.postgresql.test_dashboard import service
from tests.postgresql.test_pool_capacity import staffing


def test_lateness_counts_all_filtered_statuses_and_ignores_deleted_tasks(staffing):
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.project_task SET progress_pct=100')
        connection.execute("UPDATE eppm.project SET status='Completed' WHERE id=1")
        connection.execute("UPDATE eppm.project_task SET progress_pct=50,start_date='2026-01-01',end_date='2026-01-02' WHERE project_id=1")
    dashboard = service(staffing, 4, today=lambda: date(2026, 1, 3))
    report = dashboard.report([1, 2, 3])
    assert report.late_project_count == 1
    assert report.project_count == 3
    assert round(report.late_project_percentage, 2) == 33.33
    assert dashboard.report([2, 3]).late_project_percentage == 0
    assert dashboard.report([1]).late_project_percentage == 100
    assert service(staffing, 4, today=lambda: date(2026, 1, 2)).report([1]).late_project_count == 0
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.project_task SET is_deleted=true WHERE project_id=1')
    assert dashboard.report([1]).late_project_count == 0


def test_non_current_tasks_do_not_make_project_late(staffing):
    with psycopg.connect(staffing.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.project_task SET progress_pct=100')
        connection.execute("UPDATE eppm.project_task SET progress_pct=0,start_date='2026-01-01',end_date='2026-01-02' WHERE project_id=1")
        connection.execute('UPDATE eppm.project_plan SET is_current=false WHERE project_id=1')
    assert service(staffing, 4).report([1]).late_project_count == 0

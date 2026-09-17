"""Authorized manager memberships drive the cascading dashboard panel."""

import psycopg

from tests.postgresql.test_dashboard import service


def seed_organization(authorized):
    """Install two hierarchy paths, one incomplete path, and four projects."""
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.hierarchy_type(id,code) VALUES (101,'service'),(102,'division'),(103,'equipe')")
        connection.execute("INSERT INTO eppm.function(function_id,name,hierarchy_level) VALUES (101,'PM Alpha',5),(102,'PM Beta',5),(103,'PM Vacant',5)")
        connection.execute("INSERT INTO eppm.employee(employee_code,firstname,lastname,email,function_id) VALUES ('A','Alice','Manager','alice@example.test',101)")
        connection.execute("""INSERT INTO eppm.team(team_id,team_name,hierarchy_type_id,parent_team_id) VALUES
            (101,'Service A',101,NULL),(102,'Division A',102,101),(103,'Team A',103,102),
            (104,'Service B',101,NULL),(105,'Division B',102,104),(106,'Team B',103,105),
            (107,'Private service',101,NULL)""")
        connection.execute('INSERT INTO eppm.team_function(team_id,function_id) VALUES (103,101),(106,102),(107,103)')
        connection.execute('UPDATE eppm.project SET function_id=101 WHERE id=1')
        connection.execute('UPDATE eppm.project SET function_id=102 WHERE id=2')
        connection.execute('UPDATE eppm.project SET function_id=103 WHERE id=3')
        connection.execute("INSERT INTO eppm.project(id,name,status) VALUES (4,'Unassigned','In Progress')")
        connection.execute("UPDATE eppm.project SET status='In Progress' WHERE id IN (1,2)")
        connection.execute("UPDATE eppm.project SET status='Completed' WHERE id=3")


def test_catalog_uses_manager_memberships_parents_and_scoped_labels(authorized):
    seed_organization(authorized)
    dashboard = service(authorized)
    catalog = dashboard.catalog()
    assert catalog.labels['service'] == {'101': 'Service A', '104': 'Service B'}
    assert catalog.labels['org_manager'] == {'101': 'Alice Manager', '102': 'PM Beta'}
    assert 'Private service' not in str(catalog)
    first = catalog.projects[0]['fields']
    assert (first['service'], first['division'], first['org_team'], first['org_manager']) == (['101'], ['102'], ['103'], ['101'])
    assert dashboard.organization_choices(catalog, {}, 'service') == ['101', '104']
    assert dashboard.organization_choices(catalog, {'service': ['101']}, 'division') == ['102']
    assert dashboard.organization_choices(catalog, {'service': ['101'], 'division': ['102']}, 'org_team') == ['103']
    admin = service(authorized, 4)
    all_catalog = admin.catalog()
    assert [row['id'] for row in admin.filtered(all_catalog, {'service': ['']})] == [4]
    assert [row['id'] for row in admin.filtered(all_catalog, {'org_manager': ['']})] == [4]
    assert [row['id'] for row in admin.filtered(all_catalog, {'division': ['']})] == [3, 4]
    assert [row['id'] for row in admin.filtered(all_catalog, {'service': ['101', '104']})] == [1, 2]
    before = dashboard.revision()
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('UPDATE eppm.team SET parent_team_id=104 WHERE team_id=102')
    assert dashboard.revision() != before
    assert dashboard.catalog().projects[0]['fields']['service'] == ['104']

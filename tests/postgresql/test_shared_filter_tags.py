"""Keep dictionary and free project tags scoped through the shared filters."""

import psycopg

from app.application.services.access import AccessService
from app.application.services.business_access import BusinessAccess
from app.domain.access.models import Actor
from app.main import create_dashboard_service
from app.runtime import RuntimeResources
from tests.postgresql.business import business
from tests.postgresql.conftest import PostgreSQLFixture


type ScopedBusiness = tuple[
    RuntimeResources, AccessService, Actor, BusinessAccess, BusinessAccess
]


def test_shared_filter_tags_include_both_sources_without_hidden_labels(
    business: ScopedBusiness, pg_database: PostgreSQLFixture,
) -> None:
    """Prefer dictionary labels and include only nonempty authorized free tags."""
    resources, _, _, editor, manager = business
    with psycopg.connect(pg_database.operator_url) as connection:
        tag_id = connection.execute(
            "INSERT INTO eppm.tag_dictionnary(tag) "
            "VALUES ('Dictionary visible') RETURNING id"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO eppm.project_tag(project_id,tag_id,free_tag) "
            "VALUES (1,%s,'Ignored fallback')", (tag_id,),
        )
        connection.execute(
            "INSERT INTO eppm.project_tag(project_id,free_tag) "
            "VALUES (1,'Free visible'),(1,''),(1,NULL),(2,'Private free tag')"
        )
    service = create_dashboard_service(resources, access=editor)
    catalog = service.catalog()

    assert service.choices(catalog, {}, '_project_tags') == [
        'Dictionary visible', 'Free visible',
    ]
    assert [row['id'] for row in catalog.projects] == [1]
    for label in ('Dictionary visible', 'Free visible'):
        assert [row['id'] for row in service.filtered(
            catalog, {'_project_tags': [label]},
        )] == [1]
    privileged = create_dashboard_service(resources, access=manager)
    assert 'Private free tag' in privileged.choices(
        privileged.catalog(), {}, '_project_tags',
    )

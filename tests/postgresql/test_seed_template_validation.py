"""Native demo generation never invents missing categorical choices."""

import random

import psycopg
import pytest

from app.application.services.business_access import BusinessAccess
from app.infrastructure.postgresql.projects import PostgresProjectStore
from app.infrastructure.postgresql.seed_catalog import sample_values
from app.main import create_schema_service
from app.runtime import RuntimeResources
from tests.postgresql.conftest import AuthorizedFixture
from tests.postgresql.ui import runtime as runtime, access as access


@pytest.mark.parametrize("kind", ["ENUM", "MULTI_ENUM", "TAGS"])
@pytest.mark.parametrize("mandatory", [False, True])
def test_seed_values_never_invent_a_category_when_the_template_has_no_options(
    runtime: RuntimeResources, access: BusinessAccess, authorized: AuthorizedFixture,
    kind: str, mandatory: bool,
) -> None:
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("DELETE FROM eppm.project")
        accounts_before = connection.execute("SELECT count(*) FROM eppm.app_user").fetchone()
    schema = create_schema_service(runtime, access=access)
    schema.create_parameter("EMPTY", None, "Empty category", kind, mandatory=mandatory)
    with psycopg.connect(authorized.setup.operator_url) as connection:
        template = PostgresProjectStore(connection).template(1)
        if mandatory:
            with pytest.raises(ValueError, match="Cannot seed required property EMPTY: no configured options"):
                sample_values(template, {}, 0, random.Random(1))
        else:
            assert sample_values(template, {}, 0, random.Random(1)) == {}
        assert connection.execute("SELECT count(*) FROM eppm.project").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM eppm.schema_param_options").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM eppm.app_user").fetchone() == accounts_before

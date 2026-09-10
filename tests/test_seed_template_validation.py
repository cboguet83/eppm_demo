"""Demo generation respects empty categorical dictionaries in persisted templates."""

from contextlib import closing
from pathlib import Path
import random

import pytest

from app.infrastructure.database.connection import get_db
from app.infrastructure.database.demo_catalog import sample_values
from app.infrastructure.database.schema_init import init_db
from app.operator_services import create_schema_service


@pytest.mark.parametrize("kind", ["ENUM", "MULTI_ENUM", "TAGS"])
@pytest.mark.parametrize("mandatory", [False, True])
def test_seed_values_never_invent_a_category_when_the_template_has_no_options(tmp_path: Path, kind, mandatory):
    path = str(tmp_path / "empty-options.db")
    init_db(path)
    schema = create_schema_service(path)
    schema.create_parameter("EMPTY", None, "Empty category", kind, mandatory=mandatory)
    with closing(get_db(path)) as connection:
        if mandatory:
            with pytest.raises(ValueError, match="Cannot seed required property EMPTY: no configured options"):
                sample_values(connection, 1, 0, random.Random(1))
        else:
            assert sample_values(connection, 1, 0, random.Random(1)) == {}
        assert connection.execute("SELECT * FROM project").fetchall() == []
        assert connection.execute("SELECT * FROM schema_param_options").fetchall() == []
        assert connection.execute("SELECT * FROM app_user").fetchall() == []

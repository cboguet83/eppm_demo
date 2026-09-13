"""Storage-independent login destination validation."""

import pytest


@pytest.mark.parametrize('query', [{'nav':'https://untrusted.example.test'}, {'nav':'planning','project_id':'9'*1000}, {'nav':'portfolio','project_id':'-1'}])
def test_login_destination_never_accepts_external_or_invalid_identifiers(query):
    from app.infrastructure.authentication.http import login_destination
    destination=login_destination(query)
    assert destination.startswith('/') and 'untrusted' not in destination and 'project_id' not in destination

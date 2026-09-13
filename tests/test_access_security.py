"""Storage-independent access scope and session-configuration validation."""

import pytest

from app.application.services.access import SessionLimits
from app.domain.access.models import normalize_scope


@pytest.mark.parametrize("configuration", [
    {"idle_seconds": 0}, {"idle_seconds": -1}, {"reauthentication_seconds": True},
])
def test_invalid_session_deadlines_are_rejected_before_constructing_a_policy(configuration):
    with pytest.raises(ValueError, match="positive integer seconds"):
        SessionLimits(**configuration)


@pytest.mark.parametrize("operator,reference", [("", "request-17"), ("deployment", "")])
def test_deployment_actor_requires_both_operator_attribution_and_correlation_reference(operator, reference):
    from app.domain.access.models import DeploymentActor

    with pytest.raises(ValueError, match="explicit operator and correlation"):
        DeploymentActor(operator, reference)


@pytest.mark.parametrize("scope", [None, {}, {"kind":"projects", "project_ids":[]},
    {"kind":"projects", "project_ids":[True]}, {"kind":"all", "conditions":[{}]},
    {"kind":"properties", "conditions":[]}, {"kind":"all", "sql":"SELECT *"},
    {"kind":"properties", "conditions":[{"property_id":"project_type_id", "operator":"eq", "value_ids":[1,2]}]},
])
def test_malformed_scopes_are_rejected(scope):
    with pytest.raises(ValueError):
        normalize_scope(scope)

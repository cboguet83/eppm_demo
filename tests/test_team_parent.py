"""Team ancestry validation and parent selector regression tests."""

import pytest
from streamlit.testing.v1 import AppTest

from app.domain.organization.models import Team
from app.domain.organization.rules import normalize_team, validate_team_parent


@pytest.mark.parametrize('parent', [0, -1, True, '1', 1.5, 9223372036854775808])
def test_parent_identifier_requires_a_positive_bigint(parent):
    with pytest.raises(ValueError, match='valid team identifier'):
        normalize_team(Team('Child', parent_team_id=parent))


def test_optional_parent_validation_preserves_links_and_rejects_cycles():
    assert normalize_team(Team(' Root ')) == Team('Root')
    root = Team('Root', team_id=1)
    child = Team('Child', team_id=2, parent_team_id=1)
    grandchild = Team('Leaf', team_id=3, parent_team_id=2)
    validate_team_parent(grandchild, [root, child])
    with pytest.raises(ValueError, match='own parent'):
        normalize_team(Team('Self', team_id=1, parent_team_id=1))
    with pytest.raises(ValueError, match='circular'):
        validate_team_parent(Team('Root', team_id=1, parent_team_id=3), [root, child, grandchild])
    with pytest.raises(ValueError, match='no longer exists'):
        validate_team_parent(Team('Missing', parent_team_id=9), [root])
    with pytest.raises(ValueError, match='circular'):
        validate_team_parent(Team('New', parent_team_id=2), [
            Team('Cycle A', team_id=2, parent_team_id=3),
            Team('Cycle B', team_id=3, parent_team_id=2),
        ])


def selector_screen():
    """Supply a static catalog at the UI's application-service boundary."""
    from app.domain.organization.models import Team
    from app.presentation.components.organization_dialogs import _parent_team_selector
    from app.presentation.i18n import set_current_locale

    set_current_locale('en')
    class Catalog:
        def get_all_teams(self):
            return [Team('Root', team_id=1), Team('Child', team_id=2, parent_team_id=1),
                    Team('Leaf', team_id=3, parent_team_id=2), Team('Other', team_id=4)]
    _parent_team_selector(Catalog(), Team('Child', team_id=2, parent_team_id=1))


def test_parent_selector_excludes_self_and_descendants_and_allows_clearing():
    app = AppTest.from_function(selector_screen).run()
    assert not app.exception
    assert app.selectbox[0].options == ['No parent team', 'Root (#1)', 'Other (#4)']
    assert app.selectbox[0].value == 1
    app.selectbox[0].set_value(0).run()
    assert app.selectbox[0].value == 0

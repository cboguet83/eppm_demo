"""Organization filter paths and OR-within/AND-between facet semantics."""

from app.domain.dashboard import matches
from app.domain.organization.project_filters import FilterTeam, manager_team_facets


def test_memberships_include_classified_ancestors_and_union_multiple_paths():
    teams = {1: FilterTeam(1, 'Service A', 'service', None),
             2: FilterTeam(2, 'Division A', 'division', 1),
             3: FilterTeam(3, 'Team A', 'equipe', 2),
             4: FilterTeam(4, 'Service B', 'service', None),
             5: FilterTeam(5, 'Team B', 'team', 4)}
    result = manager_team_facets(teams, [(3, 10), (5, 10), (1, 11)])
    assert result[10] == {'service': ['1', '4'], 'division': ['2'], 'org_team': ['3', '5']}
    assert result[11] == {'service': ['1'], 'division': [''], 'org_team': ['']}


def test_cycles_unknown_parents_and_unclassified_memberships_terminate():
    teams = {1: FilterTeam(1, 'Service', 'service', 2),
             2: FilterTeam(2, 'Division', 'division', 1),
             3: FilterTeam(3, 'Other', None, 999)}
    result = manager_team_facets(teams, [(1, 10), (3, 11), (999, 12)])
    assert result[10] == {'service': ['1'], 'division': ['2'], 'org_team': ['']}
    assert result[11] == result[12] == {'service': [''], 'division': [''], 'org_team': ['']}


def test_organization_selections_remain_or_even_with_advanced_match_all():
    project = {'id': 1, 'name': 'Example', 'fields': {'service': ['1'], 'division': ['2'], 'org_manager': ['4']}}
    assert matches(project, {})
    assert matches(project, {'service': ['1', '3'], 'org_manager': ['4', '5']}, True)
    assert not matches(project, {'service': ['1'], 'division': ['3']})

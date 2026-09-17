"""Project-manager organization facets shared by portfolio-facing pages."""

from collections.abc import Iterable
from dataclasses import dataclass


ORGANIZATION_FACETS = ('service', 'division', 'org_team', 'org_manager')


@dataclass(frozen=True)
class FilterTeam:
    """Minimal team classification and parent needed for organization filters."""

    id: int
    name: str
    code: str | None
    parent_id: int | None


def manager_team_facets(
    teams: dict[int, FilterTeam], memberships: Iterable[tuple[int, int]],
) -> dict[int, dict[str, list[str]]]:
    """Resolve direct memberships and their ancestors, stopping at cycles.

    Stable hierarchy codes define categories; ``equipe`` is the existing team
    code. Missing classifications are represented by the empty-string choice.
    Multiple memberships are unions within a category.
    """
    categories = {'service': 'service', 'division': 'division', 'equipe': 'org_team', 'team': 'org_team'}
    resolved: dict[int, dict[str, set[str]]] = {}
    for team_id, function_id in memberships:
        facets = resolved.setdefault(function_id, {key: set() for key in ORGANIZATION_FACETS[:-1]})
        seen: set[int] = set()
        while team_id in teams and team_id not in seen:
            seen.add(team_id)
            team = teams[team_id]
            category = categories.get(team.code or '')
            if category:
                facets[category].add(str(team.id))
            if team.parent_id is None:
                break
            team_id = team.parent_id
    return {identity: {key: sorted(values, key=int) or [''] for key, values in facets.items()}
            for identity, facets in resolved.items()}

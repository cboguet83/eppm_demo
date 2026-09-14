"""Bounded status proportions for generated demonstration portfolios."""

import random


def project_statuses(count: int, rng: random.Random) -> list[str]:
    """Shuffle exact integer quotas, rounding capped categories down.

    Completed projects use 10%, Cancelled at most 5%, Draft at most 4%, and
    On Hold at most 3%. Remaining projects are In Progress.
    """
    if type(count) is not int or count < 0:
        raise ValueError('Project count must be a nonnegative integer.')
    statuses = [status for status, percent in
                (('Completed', 10), ('Cancelled', 5), ('Draft', 4), ('On Hold', 3))
                for _ in range(count * percent // 100)]
    statuses.extend(['In Progress'] * (count - len(statuses)))
    rng.shuffle(statuses)
    return statuses

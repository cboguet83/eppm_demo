"""Single-parent pool trees and leaf-only allocation rules, without I/O."""

from collections import defaultdict
from collections.abc import Iterable

from app.domain.resources.models import ResourcePool


class PoolHierarchy:
    """Index a validated forest once for bounded, iterative traversal."""

    def __init__(self, pools: Iterable[ResourcePool]) -> None:
        """Reject missing parents, invalid identities and cycles in a snapshot."""
        self.pools = {pool.id: pool for pool in pools}
        self.children: dict[int, list[int]] = defaultdict(list)
        for identity, pool in self.pools.items():
            if type(identity) is not int or identity <= 0:
                raise ValueError("Pool identities must be positive integers.")
            parent = pool.parent_pool_id
            if parent is not None:
                if type(parent) is not int or parent not in self.pools:
                    raise ValueError("The parent pool no longer exists.")
                self.children[parent].append(identity)
        completed: set[int] = set()
        for identity in self.pools:
            path: set[int] = set()
            current = identity
            while current is not None and current not in completed:
                if current in path:
                    raise ValueError("Pool parent links cannot be circular.")
                path.add(current)
                current = self.pools[current].parent_pool_id
            completed.update(path)

    def descendants(self, identity: int, *, leaves_only: bool = False) -> list[int]:
        """Return descendants, including the selected pool when it is a leaf."""
        if identity not in self.pools:
            raise ValueError("This pool no longer exists.")
        result: list[int] = []
        pending = [identity]
        while pending:
            current = pending.pop()
            children = self.children.get(current, [])
            if not leaves_only or not children:
                result.append(current)
            pending.extend(children)
        return sorted(result)

    def require_leaf(self, identity: int) -> None:
        """Reject allocation or direct capacity configuration on a container."""
        if identity not in self.pools:
            raise ValueError("This pool no longer exists.")
        if self.children.get(identity):
            raise ValueError(
                f'“{self.pools[identity].name}” contains child pools. '
                "Only pools without children can be assigned or have direct capacity configured."
            )

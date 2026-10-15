"""Routing algorithms, recorded step by step.

Two families, and the syllabus wants the contrast between them:

* **Link state (OSPF)** — every router learns the whole map, then runs Dijkstra
  on it by itself. :func:`dijkstra` returns one snapshot per iteration.
* **Distance vector (RIP)** — no router ever sees the map; each one only swaps
  distance tables with its neighbours and trusts what it is told. That trust is
  exactly why :func:`count_to_infinity` can happen.

Both return their intermediate state rather than just an answer, because the
convergence is the thing being taught.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field as dc_field

__all__ = [
    "Topology",
    "Link",
    "DijkstraStep",
    "dijkstra",
    "DistanceVectorRound",
    "distance_vector",
    "routing_table",
    "path_between",
]

INFINITY = 16  # RIP treats 16 as unreachable, which is what caps the counting


@dataclass(frozen=True)
class Link:
    a: str
    b: str
    cost: int = 1

    def other(self, node: str) -> str:
        return self.b if node == self.a else self.a

    def touches(self, node: str) -> bool:
        return node in (self.a, self.b)


@dataclass
class Topology:
    """An undirected weighted graph of routers."""

    nodes: list[str] = dc_field(default_factory=list)
    links: list[Link] = dc_field(default_factory=list)
    positions: dict[str, tuple[float, float]] = dc_field(default_factory=dict)

    def add_node(self, name: str, x: float = 0.0, y: float = 0.0) -> None:
        if name not in self.nodes:
            self.nodes.append(name)
        self.positions[name] = (x, y)

    def add_link(self, a: str, b: str, cost: int = 1) -> None:
        if a == b:
            raise ValueError("a router cannot link to itself")
        self.remove_link(a, b)
        self.links.append(Link(a, b, cost))

    def remove_link(self, a: str, b: str) -> bool:
        for link in list(self.links):
            if {link.a, link.b} == {a, b}:
                self.links.remove(link)
                return True
        return False

    def cost(self, a: str, b: str) -> float:
        for link in self.links:
            if {link.a, link.b} == {a, b}:
                return link.cost
        return math.inf

    def neighbours(self, node: str) -> list[str]:
        return [link.other(node) for link in self.links if link.touches(node)]


# --------------------------------------------------------------------------
# Link state — Dijkstra
# --------------------------------------------------------------------------


@dataclass
class DijkstraStep:
    """The algorithm's state after one node has been settled."""

    iteration: int
    settled: str | None
    visited: list[str]
    distance: dict[str, float]
    previous: dict[str, str | None]
    tentative: list[str]
    note: str = ""


def dijkstra(topology: Topology, source: str) -> list[DijkstraStep]:
    """Shortest paths from ``source``, one snapshot per settled node."""
    if source not in topology.nodes:
        raise ValueError(f"unknown router: {source}")

    distance = {node: math.inf for node in topology.nodes}
    previous: dict[str, str | None] = {node: None for node in topology.nodes}
    distance[source] = 0.0
    visited: list[str] = []
    steps = [
        DijkstraStep(
            iteration=0,
            settled=None,
            visited=[],
            distance=dict(distance),
            previous=dict(previous),
            tentative=sorted(topology.nodes),
            note=f"Start at {source} with cost 0; every other router is unreachable so far.",
        )
    ]

    while True:
        unvisited = [node for node in topology.nodes if node not in visited]
        reachable = [node for node in unvisited if distance[node] < math.inf]
        if not reachable:
            break

        current = min(reachable, key=lambda node: distance[node])
        visited.append(current)

        relaxed = []
        for neighbour in topology.neighbours(current):
            if neighbour in visited:
                continue
            candidate = distance[current] + topology.cost(current, neighbour)
            if candidate < distance[neighbour]:
                distance[neighbour] = candidate
                previous[neighbour] = current
                relaxed.append(f"{neighbour}={candidate:g}")

        steps.append(
            DijkstraStep(
                iteration=len(steps),
                settled=current,
                visited=list(visited),
                distance=dict(distance),
                previous=dict(previous),
                tentative=[node for node in topology.nodes if node not in visited],
                note=(
                    f"Settle {current} at cost {distance[current]:g}"
                    + (f"; improved {', '.join(relaxed)}" if relaxed else "; nothing improved")
                ),
            )
        )

    return steps


def path_between(previous: dict[str, str | None], source: str, target: str) -> list[str]:
    """Walk the predecessor chain back from ``target``."""
    path = []
    node: str | None = target
    seen = set()
    while node is not None and node not in seen:
        seen.add(node)
        path.append(node)
        if node == source:
            break
        node = previous.get(node)
    path.reverse()
    return path if path and path[0] == source else []


def routing_table(
    topology: Topology, source: str
) -> list[tuple[str, str, float]]:
    """(destination, next hop, cost) as the router would install it."""
    steps = dijkstra(topology, source)
    final = steps[-1]
    table = []
    for node in sorted(topology.nodes):
        if node == source:
            continue
        path = path_between(final.previous, source, node)
        if len(path) < 2:
            table.append((node, "-", math.inf))
        else:
            table.append((node, path[1], final.distance[node]))
    return table


# --------------------------------------------------------------------------
# Distance vector — RIP
# --------------------------------------------------------------------------


@dataclass
class DistanceVectorRound:
    """Every router's table after one exchange with its neighbours."""

    number: int
    tables: dict[str, dict[str, tuple[float, str | None]]]
    changed: list[str] = dc_field(default_factory=list)
    note: str = ""

    @property
    def converged(self) -> bool:
        return not self.changed


Tables = dict[str, dict[str, tuple[float, str | None]]]


def initial_tables(topology: Topology) -> Tables:
    """What every router knows before it has spoken to anyone: its own links."""
    tables: Tables = {}
    for node in topology.nodes:
        tables[node] = {node: (0.0, None)}
        for neighbour in topology.neighbours(node):
            tables[node][neighbour] = (topology.cost(node, neighbour), neighbour)
    return tables


def _exchange(
    topology: Topology, tables: Tables, split_horizon: bool
) -> tuple[Tables, list[str]]:
    """One synchronous round: every router recomputes from what it was told.

    Each table is rebuilt from scratch rather than only accepting improvements.
    That matters: a router must be able to *raise* its cost when the neighbour
    it depends on raises theirs, and an update rule that only takes cheaper
    routes can never do that -- which would quietly make count-to-infinity
    impossible to demonstrate.
    """
    updated: Tables = {}
    changed: list[str] = []

    for node in topology.nodes:
        fresh: dict[str, tuple[float, str | None]] = {node: (0.0, None)}
        for neighbour in topology.neighbours(node):
            link_cost = topology.cost(node, neighbour)

            # The directly attached neighbour itself.
            if link_cost < fresh.get(neighbour, (math.inf, None))[0]:
                fresh[neighbour] = (link_cost, neighbour)

            for destination, (cost, via) in tables.get(neighbour, {}).items():
                if destination == node:
                    continue
                if split_horizon and via == node:
                    continue  # never advertise a route back to where it came from
                candidate = min(cost + link_cost, INFINITY)
                if candidate < fresh.get(destination, (math.inf, None))[0]:
                    fresh[destination] = (candidate, neighbour)

        # Drop anything that has reached RIP's unreachable ceiling.
        fresh = {
            destination: entry
            for destination, entry in fresh.items()
            if entry[0] < INFINITY
        }
        updated[node] = fresh
        if fresh != tables.get(node, {}):
            changed.append(node)

    return updated, changed


def distance_vector(
    topology: Topology,
    max_rounds: int = 12,
    *,
    split_horizon: bool = False,
    initial: Tables | None = None,
) -> list[DistanceVectorRound]:
    """Run distributed Bellman-Ford until it settles.

    Each router starts knowing only its direct neighbours and then repeatedly
    recomputes from whatever its neighbours advertise. With ``split_horizon`` a
    router will not advertise a route back to the neighbour it learned it from,
    which is the standard fix for the two-node counting loop.

    ``initial`` seeds the tables, so a caller can converge, change the network
    and carry the now-stale beliefs forward.
    """
    tables = (
        {node: dict(table) for node, table in initial.items()}
        if initial is not None
        else initial_tables(topology)
    )

    rounds = [
        DistanceVectorRound(
            number=0,
            tables={node: dict(table) for node, table in tables.items()},
            changed=list(topology.nodes),
            note=(
                "Carrying the previous tables forward."
                if initial is not None
                else "Each router knows only its own directly attached links."
            ),
        )
    ]

    for number in range(1, max_rounds + 1):
        tables, changed = _exchange(topology, tables, split_horizon)
        rounds.append(
            DistanceVectorRound(
                number=number,
                tables={node: dict(table) for node, table in tables.items()},
                changed=changed,
                note=(
                    "Converged -- no router changed its table this round."
                    if not changed
                    else f"Updated: {', '.join(changed)}"
                ),
            )
        )
        if not changed:
            break

    return rounds


def count_to_infinity(
    topology: Topology,
    broken: tuple[str, str],
    max_rounds: int = 20,
    *,
    split_horizon: bool = False,
) -> list[DistanceVectorRound]:
    """Converge, break a link, then watch the estimates crawl upward.

    The stale tables are deliberately carried across the break. That is the
    whole mechanism: neither router can tell that its neighbour's cheap route
    to the lost destination runs back through itself, so each keeps believing
    the other and they raise their estimates one hop at a time until they reach
    RIP's ceiling of 16. That ceiling is the only reason this terminates at all.
    """
    settled = distance_vector(
        topology, max_rounds=max_rounds, split_horizon=split_horizon
    )
    stale = settled[-1].tables

    topology.remove_link(*broken)
    after = distance_vector(
        topology,
        max_rounds=max_rounds,
        split_horizon=split_horizon,
        initial=stale,
    )
    for index, entry in enumerate(after):
        entry.number = settled[-1].number + index
        if index == 0:
            entry.note = (
                f"Link {broken[0]}-{broken[1]} fails. Every router still believes "
                "what it was last told."
            )
    return settled + after[1:]

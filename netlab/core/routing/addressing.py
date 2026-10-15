"""IPv4 addressing: CIDR, subnetting, VLSM and longest-prefix matching.

The binary views matter as much as the numbers here. Any website will tell you
that 192.168.1.0/26 has 62 usable hosts; what the Network Lab page shows is
*which bits were borrowed* to get there, which is the part that actually has to
be understood.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

__all__ = [
    "Subnet",
    "parse_cidr",
    "split_equally",
    "vlsm",
    "Allocation",
    "Route",
    "longest_prefix_match",
    "address_classes",
]

FULL_MASK = 0xFFFFFFFF


def _to_int(dotted: str) -> int:
    parts = dotted.strip().split(".")
    if len(parts) != 4:
        raise ValueError(f"not an IPv4 address: {dotted!r}")
    value = 0
    for part in parts:
        octet = int(part)
        if not 0 <= octet <= 255:
            raise ValueError(f"octet out of range in {dotted!r}")
        value = (value << 8) | octet
    return value


def _to_dotted(value: int) -> str:
    return ".".join(str((value >> shift) & 0xFF) for shift in (24, 16, 8, 0))


def _binary(value: int, group: bool = True) -> str:
    bits = f"{value:032b}"
    return ".".join(bits[i : i + 8] for i in range(0, 32, 8)) if group else bits


@dataclass(frozen=True)
class Subnet:
    """One CIDR block."""

    network: int
    prefix: int
    label: str = ""

    def __post_init__(self) -> None:
        if not 0 <= self.prefix <= 32:
            raise ValueError(f"prefix /{self.prefix} out of range")

    @property
    def mask(self) -> int:
        return (FULL_MASK << (32 - self.prefix)) & FULL_MASK if self.prefix else 0

    @property
    def wildcard(self) -> int:
        return (~self.mask) & FULL_MASK

    @property
    def broadcast(self) -> int:
        return self.network | self.wildcard

    @property
    def total_addresses(self) -> int:
        return 1 << (32 - self.prefix)

    @property
    def usable_hosts(self) -> int:
        """Total minus the network and broadcast addresses.

        A /31 is a point-to-point link (RFC 3021) with both addresses usable,
        and a /32 is a single host route -- the general formula breaks for both.
        """
        if self.prefix == 32:
            return 1
        if self.prefix == 31:
            return 2
        return self.total_addresses - 2

    @property
    def first_host(self) -> int:
        return self.network if self.prefix >= 31 else self.network + 1

    @property
    def last_host(self) -> int:
        return self.broadcast if self.prefix >= 31 else self.broadcast - 1

    @property
    def cidr(self) -> str:
        return f"{_to_dotted(self.network)}/{self.prefix}"

    def contains(self, address: int) -> bool:
        return address & self.mask == self.network

    def as_dict(self) -> dict[str, str]:
        return {
            "cidr": self.cidr,
            "network": _to_dotted(self.network),
            "mask": _to_dotted(self.mask),
            "wildcard": _to_dotted(self.wildcard),
            "broadcast": _to_dotted(self.broadcast),
            "first": _to_dotted(self.first_host),
            "last": _to_dotted(self.last_host),
            "hosts": str(self.usable_hosts),
        }

    def binary_rows(self, parent_prefix: int | None = None) -> list[tuple[str, str, str]]:
        """Binary view split into (network part, borrowed part, host part).

        ``parent_prefix`` is the prefix this block was carved out of, so the
        bits that were borrowed to make it can be shown separately.
        """
        base = parent_prefix if parent_prefix is not None else self.prefix
        rows = []
        for name, value in (
            ("address", self.network),
            ("mask", self.mask),
            ("broadcast", self.broadcast),
        ):
            bits = f"{value:032b}"
            rows.append((name, bits[:base], bits[base : self.prefix] + "|" + bits[self.prefix :]))
        return rows


def parse_cidr(text: str) -> Subnet:
    """Parse ``a.b.c.d/nn``, snapping to the network address."""
    raw = text.strip()
    if "/" not in raw:
        raise ValueError("expected a prefix, for example 192.168.1.0/24")
    address_part, _, prefix_part = raw.partition("/")
    prefix = int(prefix_part)
    if not 0 <= prefix <= 32:
        raise ValueError(f"prefix /{prefix} out of range")
    address = _to_int(address_part)
    mask = (FULL_MASK << (32 - prefix)) & FULL_MASK if prefix else 0
    return Subnet(network=address & mask, prefix=prefix)


def split_equally(subnet: Subnet, count: int) -> list[Subnet]:
    """Divide a block into ``count`` equal subnets, rounded up to a power of 2."""
    if count < 1:
        raise ValueError("need at least one subnet")
    borrowed = 0
    while (1 << borrowed) < count:
        borrowed += 1
    new_prefix = subnet.prefix + borrowed
    if new_prefix > 32:
        raise ValueError(
            f"cannot split /{subnet.prefix} into {count} subnets -- "
            f"that needs /{new_prefix}"
        )
    step = 1 << (32 - new_prefix)
    return [
        Subnet(network=subnet.network + index * step, prefix=new_prefix, label=f"Subnet {index + 1}")
        for index in range(1 << borrowed)
    ]


@dataclass
class Allocation:
    """One VLSM request and the block it was given."""

    name: str
    requested: int
    subnet: Subnet
    wasted: int = 0


def vlsm(subnet: Subnet, requirements: list[tuple[str, int]]) -> list[Allocation]:
    """Variable-length subnetting: largest requirement first, no gaps.

    Sorting by size descending is what makes VLSM fit without fragmenting the
    space -- allocate a small block first and the large one may no longer have
    an aligned gap to sit in.
    """
    if not requirements:
        return []

    ordered = sorted(requirements, key=lambda item: item[1], reverse=True)
    allocations: list[Allocation] = []
    cursor = subnet.network

    for name, hosts in ordered:
        if hosts < 1:
            raise ValueError(f"{name} needs at least one host")
        # +2 for the network and broadcast addresses.
        needed = hosts + 2
        prefix = 32
        while (1 << (32 - prefix)) < needed and prefix > 0:
            prefix -= 1

        size = 1 << (32 - prefix)
        # Blocks must start on a boundary that matches their own size.
        if cursor % size:
            cursor += size - (cursor % size)
        block = Subnet(network=cursor, prefix=prefix, label=name)

        if block.broadcast > subnet.broadcast:
            raise ValueError(
                f"{name} needs {hosts} hosts (a /{prefix}), which no longer fits in "
                f"{subnet.cidr}"
            )

        allocations.append(
            Allocation(
                name=name,
                requested=hosts,
                subnet=block,
                wasted=block.usable_hosts - hosts,
            )
        )
        cursor = block.broadcast + 1

    return allocations


@dataclass(frozen=True)
class Route:
    """A routing table entry."""

    destination: Subnet
    next_hop: str
    interface: str = ""
    metric: int = 0

    @property
    def is_default(self) -> bool:
        return self.destination.prefix == 0


def longest_prefix_match(routes: list[Route], address: str | int) -> Route | None:
    """Pick the most specific matching route, as a router does.

    Specificity, not order, decides: a /30 beats a /24 beats the /0 default
    route no matter how the table is sorted.
    """
    value = _to_int(address) if isinstance(address, str) else address
    best: Route | None = None
    for route in routes:
        if route.destination.contains(value):
            if best is None or route.destination.prefix > best.destination.prefix:
                best = route
    return best


def address_classes(address: str) -> dict[str, str]:
    """Classful summary -- obsolete for routing, still on every exam paper."""
    value = _to_int(address)
    first = (value >> 24) & 0xFF
    if first < 128:
        name, default = "A", 8
    elif first < 192:
        name, default = "B", 16
    elif first < 224:
        name, default = "C", 24
    elif first < 240:
        name, default = "D (multicast)", 0
    else:
        name, default = "E (reserved)", 0

    private = (
        first == 10
        or (first == 172 and 16 <= ((value >> 16) & 0xFF) <= 31)
        or (first == 192 and ((value >> 16) & 0xFF) == 168)
    )
    return {
        "class": name,
        "default_prefix": f"/{default}" if default else "n/a",
        "private": "yes (RFC 1918)" if private else "no",
        "loopback": "yes" if first == 127 else "no",
        "binary": _binary(value),
    }


# Exported for the UI, which needs to move between forms constantly.
to_int = _to_int
to_dotted = _to_dotted
to_binary = _binary

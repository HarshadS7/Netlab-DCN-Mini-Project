"""Network Lab — addressing, subnetting, routing and forwarding.

Module 4 and CO3. The subnetting tab shows the borrowed bits in binary, which
is the only part of subnetting that is actually difficult; the routing tab runs
OSPF's Dijkstra and RIP's distance vector on the same topology so the two can
be compared step by step.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.layers import network as netlayer
from ...core.routing import addressing as ad
from ...core.routing.algorithms import (
    Topology,
    count_to_infinity,
    dijkstra,
    distance_vector,
    path_between,
    routing_table,
)
from ..theme import COLORS, MONO_FAMILY
from ..widgets.topologyview import TopologyView

__all__ = ["NetworkPage"]


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "section")
    return label


def _mono_view() -> QPlainTextEdit:
    view = QPlainTextEdit()
    font = QFont(MONO_FAMILY.split(",")[0].strip())
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSize(9)
    view.setFont(font)
    view.setReadOnly(True)
    view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    return view


def _table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setShowGrid(False)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    header = table.horizontalHeader()
    for index in range(len(headers)):
        header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)
    return table


def _fill(table: QTableWidget, rows: list[list[str]], mono_columns: set[int] = frozenset()) -> None:
    font = QFont(MONO_FAMILY.split(",")[0].strip())
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSize(9)
    table.setRowCount(0)
    for row in rows:
        index = table.rowCount()
        table.insertRow(index)
        for column, value in enumerate(row):
            cell = QTableWidgetItem(value)
            if column in mono_columns:
                cell.setFont(font)
            table.setItem(index, column, cell)


class NetworkPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(6)

        title = QLabel("Network Lab")
        title.setProperty("role", "title")
        subtitle = QLabel(
            "Subnetting with the borrowed bits shown in binary, routing algorithms "
            "run one step at a time, and longest-prefix forwarding."
        )
        subtitle.setProperty("role", "subtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(subtitle)

        tabs = QTabWidget()
        tabs.addTab(SubnetTab(), "Subnetting")
        tabs.addTab(VlsmTab(), "VLSM")
        tabs.addTab(RoutingTab(), "Routing")
        tabs.addTab(ForwardingTab(), "Forwarding")
        tabs.addTab(HeaderTab(), "IPv4 vs IPv6")
        outer.addWidget(tabs, 1)


# --------------------------------------------------------------------------
# Subnetting
# --------------------------------------------------------------------------


class SubnetTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        self.cidr = QLineEdit("192.168.1.0/24")
        self.cidr.setMaximumWidth(220)
        self.count = QSpinBox()
        self.count.setRange(1, 256)
        self.count.setValue(4)
        self.go = QPushButton("Split")
        self.go.setProperty("role", "primary")
        controls.addWidget(QLabel("Network"))
        controls.addWidget(self.cidr)
        controls.addWidget(QLabel("Into"))
        controls.addWidget(self.count)
        controls.addWidget(QLabel("subnets"))
        controls.addWidget(self.go)
        controls.addStretch(1)
        self.summary = QLabel()
        self.summary.setStyleSheet("font-weight: 600;")
        controls.addWidget(self.summary)
        layout.addLayout(controls)

        self.table = _table(
            ["Subnet", "CIDR", "Mask", "First host", "Last host", "Broadcast", "Hosts"]
        )
        layout.addWidget(self.table, 1)

        layout.addWidget(_section("BORROWED BITS — this is the part that matters"))
        self.binary = _mono_view()
        self.binary.setMaximumHeight(220)
        layout.addWidget(self.binary)

        self.go.clicked.connect(self.refresh)
        self.cidr.returnPressed.connect(self.refresh)
        self.count.valueChanged.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        try:
            parent = ad.parse_cidr(self.cidr.text())
            subnets = ad.split_equally(parent, self.count.value())
        except ValueError as error:
            self.summary.setText(f"<span style='color:{COLORS['bad']}'>{error}</span>")
            return

        borrowed = subnets[0].prefix - parent.prefix
        self.summary.setText(
            f"Borrowed {borrowed} bit(s): /{parent.prefix} → /{subnets[0].prefix}, "
            f"{len(subnets)} subnets of {subnets[0].usable_hosts} usable hosts"
        )

        rows = []
        for index, subnet in enumerate(subnets, start=1):
            info = subnet.as_dict()
            rows.append(
                [
                    f"#{index}",
                    info["cidr"],
                    info["mask"],
                    info["first"],
                    info["last"],
                    info["broadcast"],
                    info["hosts"],
                ]
            )
        _fill(self.table, rows, mono_columns={1, 2, 3, 4, 5})

        lines = [
            f"Parent {parent.cidr}",
            f"  network bits {'#' * parent.prefix}{'.' * (32 - parent.prefix)}",
            "",
            f"Borrowing {borrowed} host bit(s) makes {len(subnets)} subnets:",
            "",
            f"  {'subnet':<18}{'network part':<{parent.prefix + 2}}{'borrowed':<{borrowed + 2}}host part",
        ]
        for subnet in subnets[: min(8, len(subnets))]:
            bits = f"{subnet.network:032b}"
            lines.append(
                f"  {subnet.cidr:<18}{bits[:parent.prefix]}  "
                f"{bits[parent.prefix : subnet.prefix]}  {bits[subnet.prefix :]}"
            )
        if len(subnets) > 8:
            lines.append(f"  … and {len(subnets) - 8} more")
        lines += [
            "",
            f"Mask  {ad.to_binary(subnets[0].mask)}  = {ad.to_dotted(subnets[0].mask)}",
            f"      {'1' * subnets[0].prefix}{'0' * (32 - subnets[0].prefix)}",
            "",
            "The mask's 1 bits mark what the router compares; the 0 bits are the",
            "host space. Borrowing a bit halves the hosts and doubles the subnets.",
        ]
        self.binary.setPlainText("\n".join(lines))


# --------------------------------------------------------------------------
# VLSM
# --------------------------------------------------------------------------


class VlsmTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        self.cidr = QLineEdit("172.16.0.0/22")
        self.cidr.setMaximumWidth(200)
        self.requirements = QLineEdit("Sales:500, Engineering:200, Lab:50, WAN link:2")
        self.go = QPushButton("Allocate")
        self.go.setProperty("role", "primary")
        controls.addWidget(QLabel("Block"))
        controls.addWidget(self.cidr)
        controls.addWidget(QLabel("Requirements"))
        controls.addWidget(self.requirements, 1)
        controls.addWidget(self.go)
        layout.addLayout(controls)

        hint = QLabel(
            "Name:hosts, comma separated. Requirements are allocated largest first — "
            "allocate a small block early and the large one may no longer have an "
            "aligned gap to fit into."
        )
        hint.setStyleSheet(f"color: {COLORS['muted']}; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.verdict = QLabel()
        self.verdict.setStyleSheet("font-weight: 600;")
        self.verdict.setWordWrap(True)
        layout.addWidget(self.verdict)

        self.table = _table(
            ["Department", "Needs", "Allocated", "Mask", "Range", "Usable", "Wasted"]
        )
        layout.addWidget(self.table, 1)

        self.go.clicked.connect(self.refresh)
        self.requirements.returnPressed.connect(self.refresh)
        self.cidr.returnPressed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        try:
            block = ad.parse_cidr(self.cidr.text())
            requirements = []
            for chunk in self.requirements.text().split(","):
                if not chunk.strip():
                    continue
                name, _, hosts = chunk.partition(":")
                requirements.append((name.strip(), int(hosts)))
            allocations = ad.vlsm(block, requirements)
        except ValueError as error:
            self.verdict.setText(f"<span style='color:{COLORS['bad']}'>{error}</span>")
            return

        used = sum(allocation.subnet.total_addresses for allocation in allocations)
        wasted = sum(allocation.wasted for allocation in allocations)
        self.verdict.setText(
            f"<span style='color:{COLORS['good']}'>&#10003; All {len(allocations)} "
            f"requirements fit in {block.cidr}</span> "
            f"<span style='color:{COLORS['muted']}'>· {used} of "
            f"{block.total_addresses} addresses consumed, {wasted} usable host "
            f"addresses left unused inside the allocated blocks</span>"
        )

        rows = []
        for allocation in allocations:
            info = allocation.subnet.as_dict()
            rows.append(
                [
                    allocation.name,
                    str(allocation.requested),
                    info["cidr"],
                    info["mask"],
                    f"{info['first']} – {info['last']}",
                    info["hosts"],
                    str(allocation.wasted),
                ]
            )
        _fill(self.table, rows, mono_columns={2, 3, 4})


# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------


def default_topology() -> Topology:
    topology = Topology()
    for name, (x, y) in {
        "R1": (-200.0, 0.0),
        "R2": (-60.0, -120.0),
        "R3": (-60.0, 120.0),
        "R4": (90.0, -60.0),
        "R5": (90.0, 90.0),
        "R6": (230.0, 10.0),
    }.items():
        topology.add_node(name, x, y)
    for a, b, cost in [
        ("R1", "R2", 2),
        ("R1", "R3", 5),
        ("R2", "R3", 1),
        ("R2", "R4", 4),
        ("R3", "R5", 3),
        ("R4", "R5", 2),
        ("R4", "R6", 6),
        ("R5", "R6", 4),
    ]:
        topology.add_link(a, b, cost)
    return topology


class RoutingTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._topology = default_topology()
        self._steps: list = []
        self._index = 0
        self._mode = "OSPF"

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        self.algorithm = QComboBox()
        self.algorithm.addItems(
            ["OSPF — link state (Dijkstra)", "RIP — distance vector (Bellman-Ford)"]
        )
        self.source = QComboBox()
        self.source.addItems(self._topology.nodes)
        self.split_horizon = QCheckBox("split horizon")
        self.split_horizon.setToolTip(
            "Never advertise a route back to the neighbour you learned it from."
        )
        self.run_button = QPushButton("Run")
        self.run_button.setProperty("role", "primary")
        self.step_button = QPushButton("Step")
        self.break_button = QPushButton("Break R4–R6")
        self.break_button.setToolTip(
            "Cut a link after convergence and watch RIP count to infinity."
        )

        controls.addWidget(QLabel("Algorithm"))
        controls.addWidget(self.algorithm)
        controls.addWidget(QLabel("From"))
        controls.addWidget(self.source)
        controls.addWidget(self.split_horizon)
        controls.addWidget(self.run_button)
        controls.addWidget(self.step_button)
        controls.addWidget(self.break_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 6, 0)
        left_layout.addWidget(_section("TOPOLOGY — drag a router, double-click to set the source"))
        self.view = TopologyView()
        left_layout.addWidget(self.view, 1)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setMinimumHeight(40)
        self.note.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.note.setStyleSheet(f"color: {COLORS['muted']}; font-size: 12px;")
        left_layout.addWidget(self.note)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 0, 0, 0)
        right_layout.addWidget(_section("ROUTING TABLE"))
        self.table = _table(["Destination", "Next hop", "Cost"])
        right_layout.addWidget(self.table)
        right_layout.addWidget(_section("WORKING"))
        self.working = _mono_view()
        right_layout.addWidget(self.working, 1)
        splitter.addWidget(right)
        splitter.setSizes([620, 520])
        layout.addWidget(splitter, 1)

        self.view.set_topology(self._topology)
        self.view.nodeChosen.connect(self._set_source)
        self.run_button.clicked.connect(self.run)
        self.step_button.clicked.connect(self.step)
        self.break_button.clicked.connect(self.break_link)
        self.algorithm.currentTextChanged.connect(self.run)
        self.source.currentTextChanged.connect(self.run)
        self.split_horizon.toggled.connect(self.run)
        self.run()

    def _set_source(self, name: str) -> None:
        self.source.setCurrentText(name)

    def run(self) -> None:
        self._topology = self._topology  # keep any dragged positions
        self._mode = "OSPF" if self.algorithm.currentText().startswith("OSPF") else "RIP"
        source = self.source.currentText()
        if self._mode == "OSPF":
            self._steps = dijkstra(self._topology, source)
        else:
            self._steps = distance_vector(
                self._topology, split_horizon=self.split_horizon.isChecked()
            )
        self._index = len(self._steps) - 1
        self._show()

    def step(self) -> None:
        if not self._steps:
            self.run()
            return
        self._index = (self._index + 1) % len(self._steps)
        self._show()

    def break_link(self) -> None:
        """Converge, cut R4–R6, and carry the stale tables across the break."""
        self._mode = "RIP"
        self.algorithm.setCurrentIndex(1)
        self._steps = count_to_infinity(
            self._topology, ("R4", "R6"), split_horizon=self.split_horizon.isChecked()
        )
        self._index = 0
        self.view.set_topology(self._topology)
        self._show()

    def _show(self) -> None:
        if not self._steps:
            return
        step = self._steps[self._index]
        source = self.source.currentText()

        if self._mode == "OSPF":
            path = path_between(step.previous, source, self.source.currentText())
            self.view.set_highlight(
                settled=set(step.visited), path=[], source=source
            )
            self.note.setText(
                f"<b>Step {self._index} of {len(self._steps) - 1}</b> — {step.note}"
            )
            rows = []
            for node in sorted(self._topology.nodes):
                if node == source:
                    continue
                cost = step.distance[node]
                chain = path_between(step.previous, source, node)
                rows.append(
                    [
                        node,
                        chain[1] if len(chain) > 1 else "—",
                        "∞" if cost == float("inf") else f"{cost:g}",
                    ]
                )
            _fill(self.table, rows)

            lines = [
                f"Dijkstra from {source}, step {self._index}",
                "",
                f"  settled   {', '.join(step.visited) or '(none)'}",
                f"  tentative {', '.join(step.tentative) or '(none)'}",
                "",
                f"  {'node':<8}{'cost':>8}  path",
            ]
            for node in sorted(self._topology.nodes):
                cost = step.distance[node]
                chain = path_between(step.previous, source, node)
                lines.append(
                    f"  {node:<8}{'∞' if cost == float('inf') else f'{cost:g}':>8}  "
                    f"{' → '.join(chain) if chain else '—'}"
                )
            self.working.setPlainText("\n".join(lines))
        else:
            table = step.tables.get(source, {})
            self.view.set_highlight(
                settled=set(table) - {source}, path=[], source=source
            )
            self.note.setText(
                f"<b>Round {step.number}</b> — {step.note}"
                + (
                    ""
                    if step.number == 0
                    else f" <span style='color:{COLORS['muted']}'>"
                    f"(step {self._index} of {len(self._steps) - 1})</span>"
                )
            )
            rows = []
            for destination in sorted(self._topology.nodes):
                if destination == source:
                    continue
                entry = table.get(destination)
                rows.append(
                    [
                        destination,
                        entry[1] if entry and entry[1] else "—",
                        f"{entry[0]:g}" if entry else "unreachable",
                    ]
                )
            _fill(self.table, rows)

            nodes = sorted(self._topology.nodes)
            header = "  " + "".join(f"{node:>9}" for node in nodes)
            lines = [f"Distance vector, round {step.number}", "", "  every router's cost to every destination", "", header]
            for router in nodes:
                cells = []
                for destination in nodes:
                    entry = step.tables.get(router, {}).get(destination)
                    cells.append(f"{entry[0]:g}" if entry else "-")
                lines.append(f"{router:<2}" + "".join(f"{cell:>9}" for cell in cells))
            lines += [
                "",
                "A dash means the router currently believes the destination is",
                "unreachable. RIP treats 16 as infinity, which is the only thing",
                "that stops a routing loop from counting upward forever.",
            ]
            self.working.setPlainText("\n".join(lines))


# --------------------------------------------------------------------------
# Forwarding
# --------------------------------------------------------------------------


class ForwardingTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        self.address = QLineEdit("10.1.2.7")
        self.address.setMaximumWidth(200)
        self.go = QPushButton("Look up")
        self.go.setProperty("role", "primary")
        controls.addWidget(QLabel("Destination address"))
        controls.addWidget(self.address)
        controls.addWidget(self.go)
        controls.addStretch(1)
        layout.addLayout(controls)

        layout.addWidget(_section("ROUTING TABLE"))
        self.table = _table(["Destination", "Prefix", "Mask", "Next hop", "Matches?"])
        layout.addWidget(self.table)

        layout.addWidget(_section("LONGEST PREFIX MATCH"))
        self.working = _mono_view()
        layout.addWidget(self.working, 1)

        self.routes = [
            ad.Route(ad.parse_cidr("0.0.0.0/0"), "ISP", "wan0"),
            ad.Route(ad.parse_cidr("10.0.0.0/8"), "R2", "eth1"),
            ad.Route(ad.parse_cidr("10.1.0.0/16"), "R3", "eth2"),
            ad.Route(ad.parse_cidr("10.1.2.0/24"), "R4", "eth3"),
            ad.Route(ad.parse_cidr("10.1.2.128/25"), "R5", "eth4"),
            ad.Route(ad.parse_cidr("192.168.0.0/16"), "R6", "eth5"),
        ]

        self.go.clicked.connect(self.refresh)
        self.address.returnPressed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        try:
            value = ad.to_int(self.address.text())
        except ValueError as error:
            self.working.setPlainText(str(error))
            return

        best = ad.longest_prefix_match(self.routes, value)
        rows = []
        for route in self.routes:
            matches = route.destination.contains(value)
            rows.append(
                [
                    route.destination.cidr,
                    f"/{route.destination.prefix}",
                    ad.to_dotted(route.destination.mask),
                    f"{route.next_hop} ({route.interface})",
                    ("YES — chosen" if route is best else "yes") if matches else "no",
                ]
            )
        _fill(self.table, rows, mono_columns={0, 2})

        bits = f"{value:032b}"
        lines = [
            f"Destination {ad.to_dotted(value)}",
            f"            {ad.to_binary(value)}",
            "",
            "  Compare the leading bits of each route's prefix:",
            "",
        ]
        for route in self.routes:
            prefix = route.destination.prefix
            route_bits = f"{route.destination.network:032b}"
            matches = route.destination.contains(value)
            marker = "<== longest match, chosen" if route is best else ""
            lines.append(
                f"  /{prefix:<3} {route_bits[:prefix] or '(none)':<32} "
                f"{'match ' if matches else 'no    '} {marker}"
            )
        lines += [
            "",
            f"  Destination bits   {bits[: best.destination.prefix] if best else ''}",
            "",
            f"Chosen: {best.destination.cidr} via {best.next_hop} on {best.interface}"
            if best
            else "No route — the packet would be dropped and an ICMP unreachable sent.",
            "",
            "Specificity decides, not table order: a /25 beats a /24 beats a /16",
            "beats the /0 default route, however the table happens to be sorted.",
        ]
        self.working.setPlainText("\n".join(lines))


# --------------------------------------------------------------------------
# Header comparison
# --------------------------------------------------------------------------


class HeaderTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        note = QLabel(
            "Both headers built for the same 100-byte payload. IPv6 is twice the size "
            "and far simpler: no checksum, no fragmentation fields, no options, and a "
            "fixed length — so a router can process it without re-reading its own work."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {COLORS['muted']};")
        layout.addWidget(note)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        payload = b"x" * 100
        for view, caption in (
            (netlayer.build_ipv4(payload, "10.0.0.1", "10.0.0.2"), "IPv4 — 20 bytes"),
            (netlayer.build_ipv6(payload), "IPv6 — 40 bytes"),
        ):
            box = QWidget()
            inner = QVBoxLayout(box)
            inner.setContentsMargins(0, 0, 0, 0)
            inner.addWidget(_section(caption))
            table = _table(["Field", "Bits", "Value"])
            rows = [
                [item.name, str(item.length_bits), item.display] for item in view.fields
            ]
            _fill(table, rows, mono_columns={2})
            inner.addWidget(table)
            splitter.addWidget(box)
        layout.addWidget(splitter, 1)

        gone = QLabel(
            "<b>Dropped in IPv6:</b> Header Checksum (the link layer and transport "
            "layer both already check), IHL (the header is always 40 bytes), "
            "Identification / Flags / Fragment Offset (only the sending host may "
            "fragment), and Options (moved into extension headers)."
        )
        gone.setWordWrap(True)
        gone.setStyleSheet(
            f"background: {COLORS['panel']}; border: 1px solid {COLORS['border']};"
            f"border-radius: 9px; padding: 10px; color: {COLORS['muted']};"
        )
        layout.addWidget(gone)

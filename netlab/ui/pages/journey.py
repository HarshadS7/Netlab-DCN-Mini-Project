"""Packet Journey: the page that shows encapsulation end to end.

Everything on screen is driven by one real frame. Changing a control rebuilds
the frame immediately so the field table and hex dump stay live; pressing Send
animates that same frame across the channel and verifies it on arrival.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...core.channel import Channel, ChannelConfig
from ...core.model import Field, LayerView
from ...core.pcap import write_pcap
from ...core.stack import EncapsulationRequest, decapsulate, encapsulate
from ..theme import COLORS, layer_color
from ..widgets.fieldtable import FieldTable
from ..widgets.hexview import ByteRange, HexView
from ..widgets.packetscene import JourneyStep, PacketScene, Segment

__all__ = ["JourneyPage"]


def _card(widget: QWidget) -> QFrame:
    frame = QFrame()
    frame.setProperty("role", "card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 12)
    layout.addWidget(widget)
    return frame


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "section")
    return label


class JourneyPage(QWidget):
    """The flagship page: controls, animation, field table and hex dump."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._frame = None
        self._transmission = None
        self._result = None
        self._channel = Channel(ChannelConfig())

        self._build_ui()
        self.rebuild()

    # -- construction -------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)

        title = QLabel("Packet Journey")
        title.setProperty("role", "title")
        subtitle = QLabel(
            "One message, encapsulated into a real Ethernet frame, sent across a "
            "channel you control, and verified on arrival."
        )
        subtitle.setProperty("role", "subtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(subtitle)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_controls())
        splitter.addWidget(self._build_centre())
        splitter.addWidget(self._build_inspector())
        splitter.setSizes([250, 590, 440])
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, 1)

    def _build_controls(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(4)

        layout.addWidget(_section("MESSAGE"))
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(7)

        self.protocol = QComboBox()
        self.protocol.addItems(["HTTP", "DNS", "SMTP", "FTP"])
        self.host = QLineEdit("example.com")
        self.path = QLineEdit("/index.html")
        form.addRow("Protocol", self.protocol)
        form.addRow("Host", self.host)
        form.addRow("Path", self.path)
        layout.addLayout(form)

        layout.addWidget(_section("ADDRESSING"))
        address_form = QFormLayout()
        address_form.setContentsMargins(0, 0, 0, 0)
        address_form.setSpacing(7)
        self.src_ip = QLineEdit("10.0.0.1")
        self.dst_ip = QLineEdit("10.0.0.2")
        self.ttl = QLineEdit("64")
        address_form.addRow("Source IP", self.src_ip)
        address_form.addRow("Dest IP", self.dst_ip)
        address_form.addRow("TTL", self.ttl)
        layout.addLayout(address_form)

        layout.addWidget(_section("CHANNEL"))
        self.ber, ber_row = self._slider("Bit error rate", 0, 200, 0, self._format_ber)
        self.loss, loss_row = self._slider(
            "Loss probability", 0, 100, 0, lambda v: f"{v}%"
        )
        self.bandwidth, bandwidth_row = self._slider(
            "Bandwidth", 1, 100, 10, lambda v: f"{v / 10:.1f} Mbps"
        )
        layout.addLayout(ber_row)
        layout.addLayout(loss_row)
        layout.addLayout(bandwidth_row)

        self.in_router = QCheckBox("Corrupt inside a router")
        self.in_router.setToolTip(
            "Ethernet's FCS is per-hop, so a router rebuilds it after routing.\n"
            "Damage done inside a router therefore passes the next hop's FCS and\n"
            "only the end-to-end IP and TCP checksums can catch it. Tick this to\n"
            "see those checksums actually do their job."
        )
        layout.addWidget(self.in_router)

        layout.addSpacing(8)
        self.send_button = QPushButton("Send")
        self.send_button.setProperty("role", "primary")
        self.step_button = QPushButton("Step")
        self.reset_button = QPushButton("Reset")
        buttons = QHBoxLayout()
        buttons.addWidget(self.send_button)
        buttons.addWidget(self.step_button)
        buttons.addWidget(self.reset_button)
        layout.addLayout(buttons)

        self.export_button = QPushButton("Export .pcap for Wireshark")
        layout.addWidget(self.export_button)

        layout.addStretch(1)

        self.stats = QLabel()
        self.stats.setWordWrap(True)
        self.stats.setStyleSheet(f"color: {COLORS['muted']}; font-size: 11px;")
        layout.addWidget(self.stats)

        for widget in (self.host, self.path, self.src_ip, self.dst_ip, self.ttl):
            widget.editingFinished.connect(self.rebuild)
        self.protocol.currentTextChanged.connect(self.rebuild)
        self.send_button.clicked.connect(self._send)
        self.step_button.clicked.connect(self._step)
        self.reset_button.clicked.connect(self._reset)
        self.export_button.clicked.connect(self._export)

        return panel

    def _slider(self, label, low, high, value, formatter):
        row = QVBoxLayout()
        row.setSpacing(2)
        caption = QLabel()
        caption.setStyleSheet(f"color: {COLORS['muted']}; font-size: 11px;")
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        slider.setValue(value)

        def refresh(new_value: int) -> None:
            caption.setText(f"{label}: {formatter(new_value)}")

        refresh(value)
        slider.valueChanged.connect(refresh)
        row.addWidget(caption)
        row.addWidget(slider)
        return slider, row

    @staticmethod
    def _format_ber(value: int) -> str:
        return "0 (clean)" if value == 0 else f"1 in {max(1, 20000 // value)} bits"

    def _build_centre(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(8)

        self.scene = PacketScene()
        self.scene.setMinimumHeight(300)
        layout.addWidget(self.scene, 1)

        self.caption = QLabel("Press Send to start the journey.")
        self.caption.setWordWrap(True)
        self.caption.setStyleSheet("font-size: 14px; font-weight: 600; padding: 2px;")
        layout.addWidget(self.caption)

        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color: {COLORS['muted']}; font-size: 12.5px;")
        self.note.setMinimumHeight(38)
        self.note.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.note)

        layout.addWidget(_section("RECEIVER CHECKS"))
        self.checks = QLabel("The receiver has not seen a frame yet.")
        self.checks.setWordWrap(True)
        self.checks.setTextFormat(Qt.TextFormat.RichText)
        self.checks.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.checks.setStyleSheet(
            f"background: {COLORS['panel']}; border: 1px solid {COLORS['border']};"
            f"border-radius: 9px; padding: 10px; color: {COLORS['muted']};"
            "font-size: 12px;"
        )
        layout.addWidget(self.checks, 1)

        self.verdict = QLabel("")
        self.verdict.setWordWrap(True)
        self.verdict.setStyleSheet("font-size: 13px; font-weight: 600;")
        layout.addWidget(self.verdict)

        self.scene.stepChanged.connect(self._on_step)
        self.scene.finished.connect(self._on_finished)
        return panel

    def _build_inspector(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Vertical)

        self.fields = FieldTable()
        self.hex = HexView()

        fields_box = QWidget()
        fields_layout = QVBoxLayout(fields_box)
        fields_layout.setContentsMargins(0, 0, 0, 0)
        fields_layout.setSpacing(2)
        fields_layout.addWidget(_section("HEADER FIELDS"))
        fields_layout.addWidget(self.fields)

        hex_box = QWidget()
        hex_layout = QVBoxLayout(hex_box)
        hex_layout.setContentsMargins(0, 0, 0, 0)
        hex_layout.setSpacing(2)
        hex_layout.addWidget(_section("FRAME BYTES"))
        hex_layout.addWidget(self.hex)

        splitter.addWidget(fields_box)
        splitter.addWidget(hex_box)
        splitter.setSizes([420, 300])

        self.fields.fieldSelected.connect(self._on_field_selected)
        self.hex.byteClicked.connect(self._on_byte_clicked)
        return splitter

    # -- model --------------------------------------------------------------

    def _request(self) -> EncapsulationRequest:
        try:
            ttl = max(1, min(255, int(self.ttl.text())))
        except ValueError:
            ttl = 64
        return EncapsulationRequest(
            app_protocol=self.protocol.currentText(),
            host=self.host.text().strip() or "example.com",
            path=self.path.text().strip() or "/",
            src_ip=self.src_ip.text().strip() or "10.0.0.1",
            dst_ip=self.dst_ip.text().strip() or "10.0.0.2",
            ttl=ttl,
        )

    def rebuild(self) -> None:
        """Rebuild the frame from the controls, without animating."""
        try:
            self._frame = encapsulate(self._request())
        except ValueError as error:
            self.verdict.setText(f"<span style='color:{COLORS['bad']}'>{error}</span>")
            return

        self._transmission = None
        self._result = None
        self.fields.set_layers(self._frame.layers)
        self.hex.set_data(self._frame.wire, self._byte_ranges())
        self.scene.set_steps(self._build_steps(), self._protocols())
        self._update_stats()
        self.verdict.setText("")
        self.caption.setText("Press Send to start the journey.")
        self.note.setText("")
        self._refresh_checks()

    def _protocols(self) -> dict[str, str]:
        protocols = {view.layer: view.protocol for view in self._frame.layers}
        protocols["Physical"] = "Bits on the wire"
        return protocols

    def _byte_ranges(self) -> list[ByteRange]:
        ranges: list[ByteRange] = []
        for view in self._frame.layers:
            if view.header:
                ranges.append(
                    ByteRange(
                        view.header_start,
                        view.header_end,
                        layer_color(view.layer),
                        f"{view.protocol} header",
                    )
                )
            if view.padding:
                ranges.append(
                    ByteRange(
                        view.padding_start,
                        view.padding_start + len(view.padding),
                        layer_color("Padding"),
                        "Ethernet padding",
                    )
                )
            if view.trailer:
                ranges.append(
                    ByteRange(
                        view.trailer_start,
                        view.trailer_start + len(view.trailer),
                        layer_color(view.layer),
                        f"{view.protocol} trailer",
                    )
                )
        app = self._frame.layers[-1]
        ranges.append(
            ByteRange(
                app.payload_start,
                app.payload_end,
                layer_color("Application"),
                f"{app.protocol} message",
            )
        )
        return ranges

    def _update_stats(self) -> None:
        frame = self._frame
        app = frame.layers[-1]
        payload = app.payload_end - app.payload_start
        overhead = len(frame.wire) - payload
        efficiency = payload / len(frame.wire) * 100
        lines = [
            f"Frame: {len(frame.wire)} bytes "
            f"({payload} payload + {overhead} overhead)",
            f"Efficiency: {efficiency:.1f}% of the wire carries user data",
        ]
        if self._transmission is not None:
            lines.append(
                f"Delay: {self._transmission.transmission_delay_ms:.2f} ms transmission "
                f"+ {self._transmission.propagation_delay_ms:.2f} ms propagation"
            )
        self.stats.setText("\n".join(lines))

    # -- the story ----------------------------------------------------------

    def _build_steps(self) -> list[JourneyStep]:
        """Turn the frame into the sequence the animation walks through."""
        frame = self._frame
        app = frame.layers[-1]
        link, net, tran = frame.layers[0], frame.layers[1], frame.layers[2]
        payload_size = app.payload_end - app.payload_start

        payload_seg = Segment(f"{app.protocol} data", "Application", payload_size)
        tran_seg = Segment(tran.protocol, "Transport", len(tran.header))
        net_seg = Segment(net.protocol, "Network", len(net.header))
        link_seg = Segment("Ethernet", "Data Link", len(link.header))
        fcs_seg = Segment("FCS", "Data Link", len(link.trailer))
        pad_seg = Segment("pad", "Padding", len(link.padding))

        after_app = [payload_seg]
        after_tran = [tran_seg, payload_seg]
        after_net = [net_seg, *after_tran]
        after_link = [link_seg, *after_net]
        if link.padding:
            after_link = [*after_link, pad_seg]
        after_link = [*after_link, fcs_seg]

        steps = [
            JourneyStep(
                f"Application builds a {app.protocol} message",
                "Application",
                "sender",
                after_app,
                note=app.summary,
            ),
            JourneyStep(
                f"{tran.protocol} adds a {len(tran.header)}-byte header",
                "Transport",
                "sender",
                after_tran,
                note=f"{tran.summary}. The checksum also covers the IP addresses "
                f"via the pseudo-header.",
            ),
            JourneyStep(
                f"IPv4 adds a {len(net.header)}-byte header",
                "Network",
                "sender",
                after_net,
                note=f"{net.summary}. Total Length now counts the transport header too.",
            ),
            JourneyStep(
                f"Ethernet adds {len(link.header)} bytes of header and a 4-byte FCS",
                "Data Link",
                "sender",
                after_link,
                note=(
                    f"{link.summary}."
                    + (
                        f" {len(link.padding)} bytes of padding bring the frame to the "
                        "60-byte minimum."
                        if link.padding
                        else ""
                    )
                ),
            ),
        ]

        corrupt_ratio = 0.0
        lost = False
        if self._transmission is not None:
            lost = not self._transmission.delivered
            if self._transmission.corrupted_bits:
                corrupt_ratio = min(
                    1.0, len(self._transmission.corrupted_bits) / (len(frame.wire) * 8) * 60
                )

        steps.append(
            JourneyStep(
                "Lost in transit" if lost else "Crossing the physical link",
                "Physical",
                "wire",
                after_link,
                corrupt_ratio=corrupt_ratio,
                failed=lost,
                note=(
                    self._transmission.summary
                    if self._transmission is not None
                    else "Bits are encoded as signals and propagate to the far end."
                ),
            )
        )
        if lost:
            return steps

        checks = {check.layer: check for check in (self._result.checks if self._result else [])}

        def add(layer: str, segments: list[Segment], caption: str) -> bool:
            check = checks.get(layer)
            failed = check is not None and not check.ok
            steps.append(
                JourneyStep(
                    caption,
                    layer,
                    "receiver",
                    segments,
                    corrupt_ratio=corrupt_ratio if failed else 0.0,
                    failed=failed,
                    note=check.detail if check else "",
                )
            )
            return failed

        if add("Data Link", after_link, "Receiver checks the frame check sequence"):
            return steps
        if add("Network", after_net, "Ethernet header stripped, IPv4 checksum verified"):
            return steps
        if add("Transport", after_tran, f"IPv4 header stripped, {tran.protocol} checksum verified"):
            return steps
        add("Application", after_app, f"{app.protocol} message delivered")
        return steps

    # -- actions ------------------------------------------------------------

    def _send(self) -> None:
        self._transmit()
        self.scene.set_steps(self._build_steps(), self._protocols())
        self.scene.play()

    def _step(self) -> None:
        if self._transmission is None or self.scene.at_end:
            self._transmit()
            self.scene.set_steps(self._build_steps(), self._protocols())
        self.scene.next_step()

    def _transmit(self) -> None:
        self._channel.config = ChannelConfig(
            bit_error_rate=self.ber.value() / 20000.0,
            loss_probability=self.loss.value() / 100.0,
            bandwidth_bps=self.bandwidth.value() / 10 * 1_000_000,
            burst_length=1,
        )
        self._channel.reseed()
        self._transmission = self._channel.transmit(self._frame.wire)

        if self.in_router.isChecked() and self._transmission.corrupted_bits:
            # Re-sign the frame so the damage survives the link-layer check.
            self._transmission = self._channel.corrupt_at(
                self._frame.wire, self._transmission.corrupted_bits, refresh_fcs=True
            )

        if self._transmission.delivered:
            self._result = decapsulate(self._transmission.received, self._frame)
            self.hex.set_data(
                self._transmission.received,
                self._byte_ranges(),
                {bit // 8 for bit in self._transmission.corrupted_bits},
            )
        else:
            self._result = None
            self.hex.set_data(self._frame.wire, self._byte_ranges())
        self._update_stats()

    def _reset(self) -> None:
        self.scene.reset()
        self.rebuild()

    def _export(self) -> None:
        if self._frame is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export frame to pcap", "netlab-capture.pcap", "Capture (*.pcap)"
        )
        if not path:
            return
        frames = [self._frame.wire]
        if self._transmission is not None and self._transmission.delivered:
            frames.append(self._transmission.received)
        write_pcap(path, frames)
        QMessageBox.information(
            self,
            "Exported",
            f"Wrote {len(frames)} frame(s) to\n{path}\n\n"
            "Open it in Wireshark: it should parse Ethernet, IPv4, "
            f"{self._frame.layers[2].protocol} and {self._frame.layers[3].protocol} "
            "with no checksum warnings.\n\n"
            "The 4-byte FCS is stripped, exactly as a real NIC strips it before "
            "handing the frame to the capture driver.",
        )

    # -- selection linking --------------------------------------------------

    def _on_field_selected(self, view: LayerView, item: Field) -> None:
        is_trailer = item in view.trailer_fields
        start, end = view.absolute_bits(item, trailer=is_trailer)
        self.hex.set_selection(
            ByteRange(start // 8, (end + 7) // 8, layer_color(view.layer), item.name)
        )
        if item.meaning:
            self.note.setText(
                f"<b style='color:{layer_color(view.layer).name()}'>{item.name}</b> "
                f"= {item.display} &nbsp;·&nbsp; {item.meaning}"
            )

    def _on_byte_clicked(self, index: int) -> None:
        if self._frame is None:
            return
        found = self._frame.field_at_bit(index * 8)
        if found is not None:
            self.fields.select_field(*found)

    def _on_step(self, index: int, caption: str, note: str) -> None:
        self.caption.setText(caption)
        self.note.setText(note)
        self._refresh_checks()

    def _refresh_checks(self) -> None:
        """List the receiver's verdict per layer, innermost check last."""
        if self._transmission is not None and not self._transmission.delivered:
            self.checks.setText(
                f"<span style='color:{COLORS['bad']}'>&#10007; Nothing arrived.</span> "
                "The frame was dropped by the channel before the receiver saw it, so "
                "no check ever ran. Loss is not an error the receiver can detect -- "
                "only the sender's timer notices."
            )
            return
        if self._result is None:
            self.checks.setText("The receiver has not seen a frame yet.")
            return

        rows = []
        for check in self._result.checks:
            mark = "&#10003;" if check.ok else "&#10007;"
            color = COLORS["good"] if check.ok else COLORS["bad"]
            rows.append(
                f"<div style='margin-bottom:5px'>"
                f"<span style='color:{color}'>{mark}</span> "
                f"<b style='color:{layer_color(check.layer).name()}'>{check.layer}</b> "
                f"<span style='color:{COLORS['muted']}'>· {check.protocol}</span><br>"
                f"<span style='color:{COLORS['muted']}'>{check.detail}</span></div>"
            )
        self.checks.setText("".join(rows))

    def _on_finished(self) -> None:
        if self._result is None:
            self.verdict.setText(
                f"<span style='color:{COLORS['bad']}'>Frame lost -- nothing arrived. "
                "TCP would time out and retransmit.</span>"
            )
            return
        if self._result.delivered:
            self.verdict.setText(
                f"<span style='color:{COLORS['good']}'>Delivered intact. "
                f"{len(self._result.payload)} bytes handed to the application.</span>"
            )
        else:
            self.verdict.setText(
                f"<span style='color:{COLORS['bad']}'>Discarded at the "
                f"{self._result.failed_at} layer.</span>"
            )

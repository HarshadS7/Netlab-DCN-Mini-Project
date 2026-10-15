"""Application Lab — the page where the networking is genuinely real.

Three tabs, all doing real socket I/O:

* **DNS** builds a query byte by byte and sends it over a real UDP socket, with
  a bundled loopback stub resolver for networks that block port 53.
* **HTTP** types an HTTP/1.1 request straight onto a TCP socket.
* **Socket Chat** runs a real server and client over loopback, in TCP or UDP,
  so the difference between the two can be shown rather than asserted.

Blocking calls run on a worker thread; Qt's own sockets are signal-driven and
stay on the UI thread, which is the reason this page is not full of threading.
"""

from __future__ import annotations

import random

import shiboken6
from PySide6.QtCore import (
    QCoreApplication,
    QObject,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QFont
from PySide6.QtNetwork import QHostAddress, QTcpServer, QTcpSocket, QUdpSocket
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.bits import hexdump
from ...core.live import dns_client, http_client
from ...core.live.stub_resolver import StubResolver
from ..theme import COLORS, MONO_FAMILY

__all__ = ["ApplicationPage"]


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


class _Signals(QObject):
    done = Signal(object)


class _Worker(QRunnable):
    """Runs one blocking socket call off the UI thread."""

    def __init__(self, function, *args, **kwargs) -> None:
        super().__init__()
        self.signals = _Signals()
        self._call = (function, args, kwargs)

    @Slot()
    def run(self) -> None:
        function, args, kwargs = self._call
        try:
            self.signals.done.emit(function(*args, **kwargs))
        except Exception as error:  # a worker must never take the app down
            self.signals.done.emit(error)


class ApplicationPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(6)

        title = QLabel("Application Lab")
        title.setProperty("role", "title")
        subtitle = QLabel(
            "Real sockets, not a simulation. Queries are built byte by byte and sent "
            "over the network; every socket call is logged as it happens."
        )
        subtitle.setProperty("role", "subtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(subtitle)

        tabs = QTabWidget()
        tabs.addTab(DnsTab(), "DNS")
        tabs.addTab(HttpTab(), "HTTP")
        tabs.addTab(ChatTab(), "Socket Chat")
        outer.addWidget(tabs, 1)


# --------------------------------------------------------------------------
# DNS
# --------------------------------------------------------------------------


class DnsTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._stub: StubResolver | None = None
        self._pool = QThreadPool.globalInstance()

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        self.domain = QLineEdit("example.com")
        self.qtype = QComboBox()
        self.qtype.addItems(["A", "AAAA", "MX", "NS", "TXT", "CNAME"])
        self.resolver = QComboBox()
        for label in dns_client.PUBLIC_RESOLVERS:
            self.resolver.addItem(label)
        self.resolver.addItem("Offline stub (127.0.0.1)")
        self.query_button = QPushButton("Send query")
        self.query_button.setProperty("role", "primary")

        for label, widget in (
            ("Domain", self.domain),
            ("Type", self.qtype),
            ("Resolver", self.resolver),
        ):
            controls.addWidget(QLabel(label))
            controls.addWidget(widget)
        controls.addWidget(self.query_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        hint = QLabel(
            "If your network blocks outbound UDP 53, pick the offline stub: it runs a real "
            "DNS server on loopback, so the sockets and the wire format stay genuine."
        )
        hint.setStyleSheet(f"color: {COLORS['muted']}; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.verdict = QLabel("Ready.")
        self.verdict.setStyleSheet("font-size: 13px; font-weight: 600; padding: 2px 0;")
        self.verdict.setWordWrap(True)
        layout.addWidget(self.verdict)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.answers = _mono_view()
        self.trace = _mono_view()
        self.wire = _mono_view()
        for widget, caption in (
            (self.answers, "PARSED RESPONSE"),
            (self.trace, "SOCKET CALLS"),
            (self.wire, "BYTES ON THE WIRE"),
        ):
            box = QWidget()
            inner = QVBoxLayout(box)
            inner.setContentsMargins(0, 0, 0, 0)
            inner.addWidget(_section(caption))
            inner.addWidget(widget)
            splitter.addWidget(box)
        splitter.setSizes([340, 320, 460])
        layout.addWidget(splitter, 1)

        self.query_button.clicked.connect(self.send)
        self.domain.returnPressed.connect(self.send)

    def _ensure_stub(self) -> StubResolver:
        if self._stub is None:
            self._stub = StubResolver()
            self._stub.start()
        return self._stub

    def send(self) -> None:
        domain = self.domain.text().strip()
        if not domain:
            return

        if self.resolver.currentText().startswith("Offline"):
            stub = self._ensure_stub()
            server, port = stub.host, stub.port
        else:
            server = dns_client.PUBLIC_RESOLVERS[self.resolver.currentText()]
            port = 53

        self.query_button.setEnabled(False)
        self.verdict.setText(f"Querying {server}:{port} …")

        worker = _Worker(
            dns_client.resolve, domain, self.qtype.currentText(), server, port, 4.0
        )
        worker.signals.done.connect(self._show)
        self._pool.start(worker)

    def _show(self, exchange) -> None:
        self.query_button.setEnabled(True)
        if isinstance(exchange, Exception):
            self.verdict.setText(
                f"<span style='color:{COLORS['bad']}'>Unexpected error: {exchange}</span>"
            )
            return

        colour = COLORS["good"] if exchange.ok else COLORS["bad"]
        mark = "&#10003;" if exchange.ok else "&#10007;"
        self.verdict.setText(
            f"<span style='color:{colour}'>{mark} {exchange.summary}</span>"
            + (
                f" <span style='color:{COLORS['muted']}'>· {exchange.elapsed_ms:.0f} ms "
                f"from {exchange.server}</span>"
                if exchange.ok
                else ""
            )
        )

        self.trace.setPlainText("\n".join(exchange.trace))

        if exchange.parsed:
            parsed = exchange.parsed
            lines = [
                f"Transaction ID  0x{parsed['id']:04X}",
                f"Response        {parsed['is_response']}",
                f"Status          {parsed['rcode']}",
                f"Recursion avail {parsed['recursion_available']}",
                "",
                "QUESTION",
            ]
            for question in parsed["questions"]:
                lines.append(f"  {question['name']}  {question['type']}")
            for title, key in (
                ("ANSWER", "answers"),
                ("AUTHORITY", "authority"),
                ("ADDITIONAL", "additional"),
            ):
                if parsed[key]:
                    lines += ["", title]
                    for record in parsed[key]:
                        lines.append(
                            f"  {record['name']}  {record['type']}  "
                            f"ttl={record['ttl']}  {record['data']}"
                        )
            self.answers.setPlainText("\n".join(lines))
        else:
            self.answers.setPlainText(exchange.error or "No response.")

        wire = []
        if exchange.query:
            wire += ["QUERY", hexdump(exchange.query), ""]
        if exchange.response:
            wire += ["RESPONSE", hexdump(exchange.response)]
        self.wire.setPlainText("\n".join(wire))


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


class HttpTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._pool = QThreadPool.globalInstance()

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        self.host = QLineEdit("example.com")
        self.path = QLineEdit("/")
        self.method = QComboBox()
        self.method.addItems(["GET", "HEAD"])
        self.fetch_button = QPushButton("Send request")
        self.fetch_button.setProperty("role", "primary")
        for label, widget in (("Host", self.host), ("Path", self.path), ("Method", self.method)):
            controls.addWidget(QLabel(label))
            controls.addWidget(widget)
        controls.addWidget(self.fetch_button)
        layout.addLayout(controls)

        hint = QLabel(
            "Plain HTTP on port 80. Many sites now redirect to HTTPS — a 301 with a "
            "Location header is a correct result, and shows the redirect mechanism."
        )
        hint.setStyleSheet(f"color: {COLORS['muted']}; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.verdict = QLabel("Ready.")
        self.verdict.setStyleSheet("font-size: 13px; font-weight: 600; padding: 2px 0;")
        self.verdict.setWordWrap(True)
        layout.addWidget(self.verdict)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.request_view = _mono_view()
        self.response_view = _mono_view()
        self.trace = _mono_view()
        for widget, caption in (
            (self.request_view, "REQUEST SENT"),
            (self.response_view, "RESPONSE RECEIVED"),
            (self.trace, "SOCKET CALLS"),
        ):
            box = QWidget()
            inner = QVBoxLayout(box)
            inner.setContentsMargins(0, 0, 0, 0)
            inner.addWidget(_section(caption))
            inner.addWidget(widget)
            splitter.addWidget(box)
        splitter.setSizes([340, 460, 320])
        layout.addWidget(splitter, 1)

        self.fetch_button.clicked.connect(self.send)
        self.host.returnPressed.connect(self.send)

    def send(self) -> None:
        host = self.host.text().strip()
        if not host:
            return
        self.fetch_button.setEnabled(False)
        self.verdict.setText(f"Connecting to {host}:80 …")

        worker = _Worker(
            http_client.fetch, host, self.path.text() or "/", 80, self.method.currentText(), 5.0
        )
        worker.signals.done.connect(self._show)
        self._pool.start(worker)

    def _show(self, exchange) -> None:
        self.fetch_button.setEnabled(True)
        if isinstance(exchange, Exception):
            self.verdict.setText(
                f"<span style='color:{COLORS['bad']}'>Unexpected error: {exchange}</span>"
            )
            return

        colour = COLORS["good"] if exchange.ok else COLORS["bad"]
        mark = "&#10003;" if exchange.ok else "&#10007;"
        detail = exchange.status_line if exchange.ok else (exchange.error or "failed")
        self.verdict.setText(
            f"<span style='color:{colour}'>{mark} {detail}</span>"
            + (
                f" <span style='color:{COLORS['muted']}'>· {exchange.elapsed_ms:.0f} ms "
                f"from {exchange.peer}</span>"
                if exchange.ok
                else ""
            )
        )

        self.request_view.setPlainText(
            exchange.request.decode("latin-1").replace("\r\n", "↵\n")
        )
        body = exchange.body.decode("latin-1", "replace")
        self.response_view.setPlainText(
            (exchange.status_line + "\n" + exchange.header_text + "\n\n" + body)
            if exchange.ok
            else (exchange.error or "")
        )
        self.trace.setPlainText("\n".join(exchange.trace))


# --------------------------------------------------------------------------
# Socket chat
# --------------------------------------------------------------------------


class ChatTab(QWidget):
    """A real client and server on loopback, in TCP or UDP.

    Everything binds to 127.0.0.1 rather than 0.0.0.0, which keeps Windows
    Firewall quiet on a lab machine where you may not have administrator
    rights to dismiss the prompt.
    """

    PORT = 51515

    def __init__(self) -> None:
        super().__init__()
        self._server: QTcpServer | None = None
        self._connections: list[QTcpSocket] = []
        self._client: QTcpSocket | None = None
        self._server_udp: QUdpSocket | None = None
        self._client_udp: QUdpSocket | None = None
        self._sent = 0
        self._received = 0
        self._dropped = 0

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(["TCP", "UDP"])
        self.start_button = QPushButton("Start server")
        self.start_button.setProperty("role", "primary")
        self.connect_button = QPushButton("Connect client")
        self.drop = QDoubleSpinBox()
        self.drop.setRange(0.0, 1.0)
        self.drop.setSingleStep(0.1)
        self.drop.setValue(0.0)
        self.drop.setPrefix("drop ")
        self.drop.setToolTip(
            "Fraction of datagrams the client throws away before sending.\n"
            "UDP only -- it models the loss UDP does nothing about."
        )
        self.reorder = QCheckBox("reorder")
        self.reorder.setToolTip("Delay every other datagram so they arrive out of order.")

        controls.addWidget(QLabel("Transport"))
        controls.addWidget(self.mode)
        controls.addWidget(self.start_button)
        controls.addWidget(self.connect_button)
        controls.addWidget(self.drop)
        controls.addWidget(self.reorder)
        controls.addStretch(1)
        self.stats = QLabel()
        self.stats.setStyleSheet(f"color: {COLORS['muted']};")
        controls.addWidget(self.stats)
        layout.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.server_log = _mono_view()
        self.client_log = _mono_view()
        for widget, caption in (
            (self.server_log, "SERVER  ·  127.0.0.1:51515"),
            (self.client_log, "CLIENT"),
        ):
            box = QWidget()
            inner = QVBoxLayout(box)
            inner.setContentsMargins(0, 0, 0, 0)
            inner.addWidget(_section(caption))
            inner.addWidget(widget)
            splitter.addWidget(box)
        layout.addWidget(splitter, 1)

        send_row = QHBoxLayout()
        self.message = QLineEdit("Hello from the client")
        self.send_button = QPushButton("Send")
        self.send_button.setEnabled(False)
        send_row.addWidget(self.message, 1)
        send_row.addWidget(self.send_button)
        layout.addLayout(send_row)

        self.note = QLabel(
            "Start the server, connect the client, then send. Switch to UDP and raise the "
            "drop rate: messages simply vanish and nobody retransmits. TCP never loses one."
        )
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color: {COLORS['muted']}; font-size: 11px;")
        layout.addWidget(self.note)

        self.start_button.clicked.connect(self.toggle_server)
        self.connect_button.clicked.connect(self.connect_client)
        self.send_button.clicked.connect(self.send_message)
        self.message.returnPressed.connect(self.send_message)
        self.mode.currentTextChanged.connect(self.reset_all)

        # Sockets outlive their log widgets during shutdown: a queued
        # disconnected signal would otherwise fire against a deleted
        # QPlainTextEdit and raise. Close everything before Qt tears the
        # widget tree down.
        application = QCoreApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self.reset_all)

        self._update_stats()

    # -- logging ------------------------------------------------------------

    def _log(self, view: QPlainTextEdit, text: str) -> None:
        # Defence in depth for signals that arrive mid-teardown.
        if shiboken6.isValid(view):
            view.appendPlainText(text)

    def _update_stats(self) -> None:
        self.stats.setText(
            f"sent {self._sent} · received {self._received} · dropped {self._dropped}"
        )

    # -- lifecycle ----------------------------------------------------------

    def reset_all(self) -> None:
        for connection in self._connections:
            if shiboken6.isValid(connection):
                connection.disconnect()
                connection.close()
        self._connections.clear()
        for socket_object in (self._client, self._server_udp, self._client_udp):
            if socket_object is not None and shiboken6.isValid(socket_object):
                socket_object.disconnect()
                socket_object.close()
        if self._server is not None and shiboken6.isValid(self._server):
            self._server.disconnect()
            self._server.close()
        self._server = self._client = None
        self._server_udp = self._client_udp = None
        self._sent = self._received = self._dropped = 0
        self.server_log.clear()
        self.client_log.clear()
        self.start_button.setText("Start server")
        self.send_button.setEnabled(False)
        self._update_stats()

    def toggle_server(self) -> None:
        if self._server is not None or self._server_udp is not None:
            self.reset_all()
            return

        if self.mode.currentText() == "TCP":
            self._server = QTcpServer(self)
            self._log(self.server_log, "socket()   AF_INET, SOCK_STREAM")
            if not self._server.listen(QHostAddress("127.0.0.1"), self.PORT):
                self._log(self.server_log, f"listen()   FAILED: {self._server.errorString()}")
                self._server = None
                return
            self._log(self.server_log, f"bind()     127.0.0.1:{self._server.serverPort()}")
            self._log(self.server_log, "listen()   waiting for a connection")
            self._server.newConnection.connect(self._accept)
        else:
            self._server_udp = QUdpSocket(self)
            self._log(self.server_log, "socket()   AF_INET, SOCK_DGRAM")
            if not self._server_udp.bind(QHostAddress("127.0.0.1"), self.PORT):
                self._log(
                    self.server_log, f"bind()     FAILED: {self._server_udp.errorString()}"
                )
                self._server_udp = None
                return
            self._log(self.server_log, f"bind()     127.0.0.1:{self.PORT}")
            self._log(self.server_log, "           no listen(), no accept() -- UDP has no connections")
            self._server_udp.readyRead.connect(self._read_udp_server)
            self.send_button.setEnabled(True)

        self.start_button.setText("Stop server")

    def _accept(self) -> None:
        connection = self._server.nextPendingConnection()
        peer = f"{connection.peerAddress().toString()}:{connection.peerPort()}"
        self._log(self.server_log, f"accept()   connection from {peer}")
        connection.readyRead.connect(lambda c=connection: self._read_tcp_server(c))
        connection.disconnected.connect(
            lambda c=connection: self._log(self.server_log, "           client disconnected")
        )
        self._connections.append(connection)

    def connect_client(self) -> None:
        if self.mode.currentText() == "TCP":
            if self._server is None:
                self._log(self.client_log, "Start the server first.")
                return
            self._client = QTcpSocket(self)
            self._log(self.client_log, "socket()   AF_INET, SOCK_STREAM")
            self._client.connected.connect(self._on_connected)
            self._client.readyRead.connect(self._read_tcp_client)
            self._client.errorOccurred.connect(
                lambda _: self._log(self.client_log, f"error      {self._client.errorString()}")
            )
            self._log(self.client_log, f"connect()  -> 127.0.0.1:{self.PORT}")
            self._client.connectToHost(QHostAddress("127.0.0.1"), self.PORT)
        else:
            self._client_udp = QUdpSocket(self)
            self._client_udp.bind(QHostAddress("127.0.0.1"), 0)
            self._log(self.client_log, "socket()   AF_INET, SOCK_DGRAM")
            self._log(
                self.client_log,
                f"bind()     127.0.0.1:{self._client_udp.localPort()} (ephemeral)",
            )
            self._log(self.client_log, "           no connect() needed -- just sendto()")
            self._client_udp.readyRead.connect(self._read_udp_client)
            self.send_button.setEnabled(True)

    def _on_connected(self) -> None:
        local = self._client.localPort()
        self._log(self.client_log, f"           connected, local port {local}")
        self._log(self.client_log, "           three-way handshake complete")
        self.send_button.setEnabled(True)

    # -- sending ------------------------------------------------------------

    def send_message(self) -> None:
        text = self.message.text()
        if not text:
            return
        payload = text.encode()

        if self.mode.currentText() == "TCP":
            if self._client is None or self._client.state() != QTcpSocket.SocketState.ConnectedState:
                self._log(self.client_log, "Not connected.")
                return
            self._client.write(payload)
            self._sent += 1
            self._log(self.client_log, f"send()     {len(payload)} bytes: {text!r}")
        else:
            if self._client_udp is None:
                self._log(self.client_log, "Connect the client first.")
                return
            self._sent += 1
            if random.random() < self.drop.value():
                self._dropped += 1
                self._log(
                    self.client_log,
                    f"send()     {text!r} DROPPED before transmission -- "
                    "UDP will not notice or retry",
                )
                self._update_stats()
                return

            delay = 300 if (self.reorder.isChecked() and self._sent % 2 == 0) else 0
            if delay:
                self._log(self.client_log, f"send()     {text!r} delayed {delay} ms (reordering)")
                QTimer.singleShot(delay, lambda p=payload: self._write_datagram(p))
            else:
                self._write_datagram(payload)
                self._log(self.client_log, f"sendto()   {len(payload)} bytes: {text!r}")
        self._update_stats()

    def _write_datagram(self, payload: bytes) -> None:
        if self._client_udp is not None:
            self._client_udp.writeDatagram(payload, QHostAddress("127.0.0.1"), self.PORT)

    # -- receiving ----------------------------------------------------------

    def _read_tcp_server(self, connection: QTcpSocket) -> None:
        data = bytes(connection.readAll().data())
        self._received += 1
        self._log(self.server_log, f"recv()     {len(data)} bytes: {data.decode(errors='replace')!r}")
        reply = b"ACK: " + data
        connection.write(reply)
        self._log(self.server_log, f"send()     replied {len(reply)} bytes")
        self._update_stats()

    def _read_tcp_client(self) -> None:
        data = bytes(self._client.readAll().data())
        self._log(self.client_log, f"recv()     {data.decode(errors='replace')!r}")

    def _read_udp_server(self) -> None:
        while self._server_udp.hasPendingDatagrams():
            datagram = self._server_udp.receiveDatagram()
            data = bytes(datagram.data().data())
            self._received += 1
            self._log(
                self.server_log,
                f"recvfrom() {len(data)} bytes from port {datagram.senderPort()}: "
                f"{data.decode(errors='replace')!r}",
            )
            self._server_udp.writeDatagram(
                b"ACK: " + data, datagram.senderAddress(), datagram.senderPort()
            )
        self._update_stats()

    def _read_udp_client(self) -> None:
        while self._client_udp.hasPendingDatagrams():
            datagram = self._client_udp.receiveDatagram()
            data = bytes(datagram.data().data())
            self._log(self.client_log, f"recvfrom() {data.decode(errors='replace')!r}")

"""An HTTP/1.1 client written directly on a TCP socket.

No ``requests``, no ``http.client`` -- the request line and headers are typed
out as bytes and pushed through ``socket.sendall``, and the reply is read back
raw. That is the point: the Application Lab shows the exact bytes that crossed
the connection, which is what "using the services of the transport layer" means
in the syllabus.
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass, field as dc_field

__all__ = ["HttpExchange", "fetch"]

MAX_BODY_PREVIEW = 2048


@dataclass
class HttpExchange:
    """One request/response pair, kept as bytes."""

    host: str
    path: str
    port: int = 80
    request: bytes = b""
    response: bytes = b""
    status_line: str = ""
    headers: list[tuple[str, str]] = dc_field(default_factory=list)
    body: bytes = b""
    elapsed_ms: float = 0.0
    trace: list[str] = dc_field(default_factory=list)
    error: str | None = None
    peer: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.status_line)

    @property
    def status_code(self) -> int | None:
        parts = self.status_line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            return int(parts[1])
        return None

    @property
    def header_text(self) -> str:
        return "\n".join(f"{name}: {value}" for name, value in self.headers)


def fetch(
    host: str,
    path: str = "/",
    port: int = 80,
    method: str = "GET",
    timeout: float = 5.0,
) -> HttpExchange:
    """Perform one HTTP/1.1 exchange over a raw TCP socket."""
    exchange = HttpExchange(host=host, path=path, port=port)

    request = (
        f"{method} {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "User-Agent: NetLab/1.0 (DCN mini project)\r\n"
        "Accept: */*\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode()
    exchange.request = request
    exchange.trace.append(f"build request    {len(request)} bytes of ASCII")

    started = time.perf_counter()
    sock = None
    try:
        # Resolve first, so a DNS failure is reported as a DNS failure.
        address = socket.gethostbyname(host)
        exchange.trace.append(f"gethostbyname()  {host} -> {address}")

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        exchange.trace.append("socket()         AF_INET, SOCK_STREAM  (TCP)")
        sock.settimeout(timeout)

        sock.connect((address, port))
        exchange.peer = f"{address}:{port}"
        exchange.trace.append(f"connect()        three-way handshake to {exchange.peer}")
        local = sock.getsockname()
        exchange.trace.append(f"                 local end is {local[0]}:{local[1]} (ephemeral)")

        sock.sendall(request)
        exchange.trace.append(f"sendall()        {len(request)} bytes")

        chunks = []
        total = 0
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                exchange.trace.append("recv()           returned 0 -- server closed the connection")
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > 64 * 1024:
                exchange.trace.append("recv()           stopping after 64 KB")
                break
        exchange.response = b"".join(chunks)
        exchange.trace.append(f"                 {total} bytes received in total")
        exchange.elapsed_ms = (time.perf_counter() - started) * 1000

        _split(exchange)
    except socket.gaierror:
        exchange.error = (
            f"Could not resolve {host}. Check the name, or that this machine has "
            "a working DNS resolver and internet access."
        )
    except socket.timeout:
        exchange.error = f"Timed out after {timeout:g}s talking to {host}:{port}."
    except ConnectionRefusedError:
        exchange.error = f"{host}:{port} refused the connection."
    except OSError as error:
        exchange.error = f"Socket error: {error}"
    finally:
        if sock is not None:
            sock.close()
            exchange.trace.append("close()          connection torn down")

    return exchange


def _split(exchange: HttpExchange) -> None:
    """Separate the status line, headers and body of the raw response."""
    raw = exchange.response
    separator = raw.find(b"\r\n\r\n")
    head = raw if separator < 0 else raw[:separator]
    exchange.body = b"" if separator < 0 else raw[separator + 4 :][:MAX_BODY_PREVIEW]

    lines = head.decode("latin-1").split("\r\n")
    if not lines or not lines[0]:
        exchange.error = "Empty response"
        return

    exchange.status_line = lines[0]
    for line in lines[1:]:
        if ":" in line:
            name, _, value = line.partition(":")
            exchange.headers.append((name.strip(), value.strip()))

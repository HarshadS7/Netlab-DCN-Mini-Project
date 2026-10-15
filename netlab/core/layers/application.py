"""Application layer message builders: HTTP, DNS, SMTP and FTP.

HTTP, SMTP and FTP are text protocols, so their "fields" are lines -- but they
are still reported as byte ranges, which means the field table and the hex dump
highlight them exactly like a binary header. DNS is genuinely binary and its
encoder is the same one the live UDP client uses, so what the Packet Journey
page draws is a query a real resolver would answer.
"""

from __future__ import annotations

import random
import struct

from ..model import Field, LayerView

__all__ = [
    "build_http_request",
    "build_http_response",
    "build_dns_query",
    "parse_dns_message",
    "build_smtp",
    "build_ftp",
    "DNS_TYPES",
]

DNS_TYPES = {1: "A", 2: "NS", 5: "CNAME", 15: "MX", 16: "TXT", 28: "AAAA"}
DNS_RCODES = {
    0: "NOERROR",
    1: "FORMERR",
    2: "SERVFAIL",
    3: "NXDOMAIN",
    4: "NOTIMP",
    5: "REFUSED",
}


def _text_fields(text: str, descriptions: dict[str, str] | None = None) -> list[Field]:
    """Turn a text protocol message into one field per line, with byte offsets."""
    descriptions = descriptions or {}
    fields: list[Field] = []
    offset = 0
    for line in text.split("\r\n"):
        raw = line.encode()
        if line:
            name = line.split(":")[0] if ":" in line else line.split(" ")[0]
            meaning = descriptions.get(name, "")
            fields.append(
                Field(name, offset * 8, (len(raw) + 2) * 8, line, meaning, raw)
            )
        offset += len(raw) + 2
    return fields


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

_HTTP_MEANINGS = {
    "GET": "Request line: method, path and version",
    "Host": "Mandatory in HTTP/1.1 -- lets one IP serve many sites",
    "User-Agent": "Identifies the client software",
    "Accept": "Media types the client can handle -- content negotiation",
    "Connection": "Whether to keep the TCP connection open for more requests",
}


def build_http_request(
    host: str = "example.com",
    path: str = "/",
    method: str = "GET",
    *,
    body: str = "",
    keep_alive: bool = True,
) -> tuple[LayerView, bytes]:
    """Build a real HTTP/1.1 request. Returns the layer view and its bytes."""
    lines = [
        f"{method} {path} HTTP/1.1",
        f"Host: {host}",
        "User-Agent: NetLab/1.0",
        "Accept: */*",
        f"Connection: {'keep-alive' if keep_alive else 'close'}",
    ]
    if body:
        lines.append(f"Content-Length: {len(body.encode())}")
    text = "\r\n".join(lines) + "\r\n\r\n" + body
    raw = text.encode()

    view = LayerView(
        layer="Application",
        protocol="HTTP",
        header=b"",
        fields=_text_fields(text, _HTTP_MEANINGS),
        summary=f"{method} {path} to {host}",
    )
    return view, raw


def build_http_response(
    status: int = 200, reason: str = "OK", body: str = "<h1>It works</h1>"
) -> tuple[LayerView, bytes]:
    text = (
        f"HTTP/1.1 {status} {reason}\r\n"
        "Server: NetLab/1.0\r\n"
        "Content-Type: text/html\r\n"
        f"Content-Length: {len(body.encode())}\r\n"
        "\r\n" + body
    )
    raw = text.encode()
    view = LayerView(
        layer="Application",
        protocol="HTTP",
        header=b"",
        fields=_text_fields(text),
        summary=f"{status} {reason}, {len(body)} bytes",
    )
    return view, raw


# --------------------------------------------------------------------------
# DNS -- binary, and shared with the live resolver client
# --------------------------------------------------------------------------


def encode_qname(domain: str) -> bytes:
    """Encode a domain as length-prefixed labels, terminated by a zero byte."""
    out = bytearray()
    for label in domain.rstrip(".").split("."):
        encoded = label.encode("idna") if any(ord(c) > 127 for c in label) else label.encode()
        if not 0 < len(encoded) <= 63:
            raise ValueError(f"bad DNS label: {label!r}")
        out.append(len(encoded))
        out += encoded
    out.append(0)
    return bytes(out)


def build_dns_query(
    domain: str = "example.com",
    qtype: str = "A",
    *,
    transaction_id: int | None = None,
    recursion_desired: bool = True,
) -> tuple[LayerView, bytes]:
    """Build a standard DNS query, byte by byte."""
    ident = transaction_id if transaction_id is not None else random.getrandbits(16)
    flags = 0x0100 if recursion_desired else 0x0000
    type_value = next((k for k, v in DNS_TYPES.items() if v == qtype.upper()), 1)

    header = struct.pack("!HHHHHH", ident, flags, 1, 0, 0, 0)
    qname = encode_qname(domain)
    question = qname + struct.pack("!HH", type_value, 1)
    raw = header + question

    name_bits = len(qname) * 8
    fields = [
        Field(
            "Transaction ID",
            0,
            16,
            f"0x{ident:04X}",
            "Matches this reply to this query -- UDP gives no other ordering",
            ident,
        ),
        Field(
            "Flags",
            16,
            16,
            f"0x{flags:04X}",
            "QR=0 query, RD=1 recursion desired" if recursion_desired else "QR=0 query",
            flags,
        ),
        Field("Questions", 32, 16, "1", "Number of entries in the question section", 1),
        Field("Answer RRs", 48, 16, "0", "Empty in a query", 0),
        Field("Authority RRs", 64, 16, "0", "Empty in a query", 0),
        Field("Additional RRs", 80, 16, "0", "Empty in a query", 0),
        Field(
            "Query Name",
            96,
            name_bits,
            domain,
            "Length-prefixed labels: " + " ".join(f"{len(p)}{p}" for p in domain.split(".")),
            qname,
        ),
        Field(
            "Query Type",
            96 + name_bits,
            16,
            f"{type_value} ({qtype.upper()})",
            "Record type being asked for",
            type_value,
        ),
        Field(
            "Query Class",
            112 + name_bits,
            16,
            "1 (IN)",
            "Internet class",
            1,
        ),
    ]

    view = LayerView(
        layer="Application",
        protocol="DNS",
        header=b"",
        fields=fields,
        summary=f"Standard query 0x{ident:04X} {qtype.upper()} {domain}",
    )
    return view, raw


def _read_name(message: bytes, offset: int) -> tuple[str, int]:
    """Read a possibly compressed domain name. Returns (name, next offset)."""
    labels: list[str] = []
    jumped = False
    end = offset
    seen = set()

    while True:
        if offset >= len(message):
            raise ValueError("DNS name runs past the end of the message")
        length = message[offset]
        if length & 0xC0 == 0xC0:  # compression pointer
            if offset + 1 >= len(message):
                raise ValueError("truncated DNS compression pointer")
            pointer = ((length & 0x3F) << 8) | message[offset + 1]
            if pointer in seen:
                raise ValueError("circular DNS compression pointer")
            seen.add(pointer)
            if not jumped:
                end = offset + 2
                jumped = True
            offset = pointer
            continue
        offset += 1
        if length == 0:
            if not jumped:
                end = offset
            break
        labels.append(message[offset : offset + length].decode("ascii", "replace"))
        offset += length

    return ".".join(labels), end


def parse_dns_message(message: bytes) -> dict:
    """Parse a DNS response, following compression pointers."""
    if len(message) < 12:
        raise ValueError("DNS message shorter than its 12-byte header")
    ident, flags, qdcount, ancount, nscount, arcount = struct.unpack(
        "!HHHHHH", message[:12]
    )

    offset = 12
    questions = []
    for _ in range(qdcount):
        name, offset = _read_name(message, offset)
        qtype, qclass = struct.unpack("!HH", message[offset : offset + 4])
        offset += 4
        questions.append({"name": name, "type": DNS_TYPES.get(qtype, str(qtype))})

    def read_records(count: int) -> list[dict]:
        nonlocal offset
        records = []
        for _ in range(count):
            name, offset = _read_name(message, offset)
            rtype, rclass, ttl, length = struct.unpack("!HHIH", message[offset : offset + 10])
            offset += 10
            data = message[offset : offset + length]
            offset += length
            records.append(
                {
                    "name": name,
                    "type": DNS_TYPES.get(rtype, str(rtype)),
                    "ttl": ttl,
                    "data": _format_rdata(message, rtype, data),
                }
            )
        return records

    answers = read_records(ancount)
    authority = read_records(nscount)
    additional = read_records(arcount)

    return {
        "id": ident,
        "flags": flags,
        "is_response": bool(flags & 0x8000),
        "recursion_available": bool(flags & 0x0080),
        "truncated": bool(flags & 0x0200),
        "rcode": DNS_RCODES.get(flags & 0x0F, str(flags & 0x0F)),
        "questions": questions,
        "answers": answers,
        "authority": authority,
        "additional": additional,
    }


def _format_rdata(message: bytes, rtype: int, data: bytes) -> str:
    if rtype == 1 and len(data) == 4:
        return ".".join(str(b) for b in data)
    if rtype == 28 and len(data) == 16:
        import ipaddress

        return str(ipaddress.IPv6Address(data))
    if rtype in (2, 5):
        try:
            return _read_name(message, message.index(data))[0]
        except (ValueError, IndexError):
            return data.hex()
    if rtype == 16 and data:
        return data[1 : 1 + data[0]].decode("ascii", "replace")
    return data.hex()


# --------------------------------------------------------------------------
# SMTP and FTP -- command/response protocols, shown as dialogues
# --------------------------------------------------------------------------


def build_smtp(
    sender: str = "student@kjsce.edu",
    recipient: str = "professor@kjsce.edu",
    subject: str = "Mini project demo",
    body: str = "Sent through NetLab.",
) -> tuple[LayerView, bytes]:
    """An SMTP DATA exchange, MIME headers included (syllabus 2.2)."""
    text = (
        f"MAIL FROM:<{sender}>\r\n"
        f"RCPT TO:<{recipient}>\r\n"
        "DATA\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        f"From: {sender}\r\n"
        f"To: {recipient}\r\n"
        f"Subject: {subject}\r\n"
        "\r\n" + body + "\r\n.\r\n"
    )
    raw = text.encode()
    view = LayerView(
        layer="Application",
        protocol="SMTP",
        header=b"",
        fields=_text_fields(
            text,
            {
                "MAIL FROM": "Envelope sender",
                "RCPT TO": "Envelope recipient",
                "DATA": "Everything until a lone dot is the message",
                "MIME-Version": "Declares MIME so non-ASCII content survives",
            },
        ),
        summary=f"Mail from {sender} to {recipient}",
    )
    return view, raw


def build_ftp(
    command: str = "RETR", argument: str = "report.pdf"
) -> tuple[LayerView, bytes]:
    """An FTP control-channel command (syllabus 2.2)."""
    text = f"{command} {argument}\r\n"
    raw = text.encode()
    view = LayerView(
        layer="Application",
        protocol="FTP",
        header=b"",
        fields=_text_fields(
            text,
            {command: "FTP uses a separate control and data connection"},
        ),
        summary=f"{command} {argument} on the control connection",
    )
    return view, raw

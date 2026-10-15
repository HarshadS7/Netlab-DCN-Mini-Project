"""Write frames to a ``.pcap`` file Wireshark can open.

This is the project's independent correctness check. If Wireshark parses an
exported frame and reports no bad checksums, then the headers this project
builds are right -- which is a far stronger claim than any screenshot.

One deliberate omission: the Ethernet FCS is stripped before writing. Wireshark
assumes captured Ethernet frames have had the FCS removed by the NIC (which is
what really happens), so including it would show the four CRC bytes as a
malformed trailer. The FCS is still built, still checked, and still shown in the
UI -- it is just not part of the capture, exactly as with a real capture.
"""

from __future__ import annotations

import struct
import time
from pathlib import Path

__all__ = ["LINKTYPE_ETHERNET", "write_pcap", "PcapWriter"]

MAGIC = 0xA1B2C3D4
VERSION_MAJOR, VERSION_MINOR = 2, 4
SNAPLEN = 65535
LINKTYPE_ETHERNET = 1

FCS_LEN = 4


def _global_header(linktype: int = LINKTYPE_ETHERNET) -> bytes:
    return struct.pack(
        "<IHHiIII", MAGIC, VERSION_MAJOR, VERSION_MINOR, 0, 0, SNAPLEN, linktype
    )


def _record(frame: bytes, timestamp: float) -> bytes:
    seconds = int(timestamp)
    microseconds = int((timestamp - seconds) * 1_000_000)
    return (
        struct.pack("<IIII", seconds, microseconds, len(frame), len(frame)) + frame
    )


def write_pcap(
    path: str | Path,
    frames: list[bytes],
    *,
    strip_fcs: bool = True,
    linktype: int = LINKTYPE_ETHERNET,
    start_time: float | None = None,
) -> Path:
    """Write ``frames`` to ``path``. Returns the path actually written."""
    target = Path(path)
    base = time.time() if start_time is None else start_time

    with target.open("wb") as handle:
        handle.write(_global_header(linktype))
        for index, frame in enumerate(frames):
            payload = frame[:-FCS_LEN] if strip_fcs and len(frame) > FCS_LEN else frame
            handle.write(_record(payload, base + index * 0.001))

    return target


class PcapWriter:
    """Append frames one at a time, for capturing a whole session."""

    def __init__(self, path: str | Path, *, strip_fcs: bool = True) -> None:
        self.path = Path(path)
        self.strip_fcs = strip_fcs
        self._count = 0
        with self.path.open("wb") as handle:
            handle.write(_global_header())

    def write(self, frame: bytes, timestamp: float | None = None) -> None:
        payload = (
            frame[:-FCS_LEN] if self.strip_fcs and len(frame) > FCS_LEN else frame
        )
        with self.path.open("ab") as handle:
            handle.write(_record(payload, timestamp or time.time()))
        self._count += 1

    @property
    def count(self) -> int:
        return self._count

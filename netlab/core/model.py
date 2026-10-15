"""The vocabulary the UI reads: fields, layers and an assembled frame.

The point of this module is that a :class:`Field` knows exactly which bits of
the wire it occupies. That is what lets the Packet Journey page keep a header
segment, the field table and the hex dump highlighted in the same colour
without any of the three re-deriving the layout for itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

__all__ = ["Field", "LayerView", "Frame", "assemble"]


@dataclass(frozen=True)
class Field:
    """One named field, positioned relative to the start of its own header."""

    name: str
    offset_bits: int
    length_bits: int
    display: str
    meaning: str = ""
    raw: int | bytes | None = None

    @property
    def end_bits(self) -> int:
        return self.offset_bits + self.length_bits


@dataclass
class LayerView:
    """One layer's contribution to the frame: a header, and maybe a trailer."""

    layer: str
    protocol: str
    header: bytes
    fields: list[Field] = dc_field(default_factory=list)
    trailer: bytes = b""
    trailer_fields: list[Field] = dc_field(default_factory=list)
    padding: bytes = b""
    summary: str = ""

    # Absolute byte offsets into ``Frame.wire``, filled in by :func:`assemble`.
    header_start: int = 0
    payload_start: int = 0
    payload_end: int = 0
    padding_start: int = 0
    trailer_start: int = 0

    @property
    def header_end(self) -> int:
        return self.header_start + len(self.header)

    def absolute_bits(self, item: Field, *, trailer: bool = False) -> tuple[int, int]:
        """Where ``item`` lives in the assembled frame, as a bit range."""
        base = (self.trailer_start if trailer else self.header_start) * 8
        return base + item.offset_bits, base + item.end_bits


@dataclass
class Frame:
    """An assembled frame plus the layer views describing how to read it."""

    layers: list[LayerView]  # outermost (link) first, innermost (application) last
    wire: bytes
    payload: bytes

    def layer(self, protocol: str) -> LayerView | None:
        for view in self.layers:
            if view.protocol.upper() == protocol.upper():
                return view
        return None

    def field_at_bit(self, index: int) -> tuple[LayerView, Field] | None:
        """Reverse lookup, so clicking a hex byte can select its field."""
        for view in self.layers:
            pairs = [(item, False) for item in view.fields]
            pairs += [(item, True) for item in view.trailer_fields]
            for item, is_trailer in pairs:
                start, end = view.absolute_bits(item, trailer=is_trailer)
                if start <= index < end:
                    return view, item
        return None


def assemble(layers: list[LayerView], payload: bytes) -> Frame:
    """Stack ``layers`` (outermost first) around ``payload`` into one frame.

    Headers are laid down front to back, then padding and trailers are appended
    in reverse, which is exactly how the bytes sit on the wire::

        [eth hdr][ip hdr][tcp hdr][payload][eth pad][eth fcs]
    """
    wire = bytearray()
    for view in layers:
        view.header_start = len(wire)
        wire += view.header

    payload_start = len(wire)
    wire += payload
    inner_end = len(wire)

    for view in reversed(layers):
        view.payload_start = view.header_end
        view.payload_end = inner_end
        view.padding_start = len(wire)
        wire += view.padding
        view.trailer_start = len(wire)
        wire += view.trailer
        inner_end = len(wire)

    # The innermost layer carries the application data itself, nothing further.
    if layers:
        layers[-1].payload_start = payload_start

    return Frame(layers=layers, wire=bytes(wire), payload=payload)

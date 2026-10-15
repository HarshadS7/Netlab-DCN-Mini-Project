"""Tests for the Qt-free network engine.

Where a published check value exists, it is used in preference to a value this
project produced itself -- a test that only asserts the code agrees with itself
would pass just as happily with the maths wrong.
"""

from __future__ import annotations

import struct

import pytest

from netlab.core import bits, pcap
from netlab.core.channel import Channel, ChannelConfig
from netlab.core.errors import crc
from netlab.core.errors.checksum import (
    checksum_steps,
    internet_checksum,
    verify_checksum,
)
from netlab.core.layers import application, datalink, network, transport
from netlab.core.model import Field, LayerView, assemble
from netlab.core.stack import EncapsulationRequest, decapsulate, encapsulate


# --------------------------------------------------------------------------
# Bit helpers
# --------------------------------------------------------------------------


def test_bits_roundtrip():
    data = bytes(range(256))
    assert bits.bits_to_bytes(bits.bytes_to_bits(data)) == data


def test_bits_are_msb_first():
    assert bits.bytes_to_bits(b"\x80") == [1, 0, 0, 0, 0, 0, 0, 0]
    assert bits.bytes_to_bits(b"\x01") == [0, 0, 0, 0, 0, 0, 0, 1]


@pytest.mark.parametrize("index", [0, 7, 8, 15])
def test_flip_bit_changes_exactly_one_bit(index):
    data = b"\x00\x00"
    flipped = bits.flip_bit(data, index)
    assert bits.bit_diff(data, flipped) == [index]


def test_flip_bit_rejects_out_of_range():
    with pytest.raises(IndexError):
        bits.flip_bit(b"\x00", 8)


def test_address_formatting_roundtrip():
    assert bits.format_ipv4(bits.parse_ipv4("192.168.1.1")) == "192.168.1.1"
    assert bits.format_mac(bits.parse_mac("02:1a:2b:3c:4d:5e")) == "02:1A:2B:3C:4D:5E"


def test_parse_ipv4_rejects_bad_octet():
    with pytest.raises(ValueError):
        bits.parse_ipv4("10.0.0.256")


# --------------------------------------------------------------------------
# Checksums -- against published vectors
# --------------------------------------------------------------------------


def test_internet_checksum_matches_canonical_ipv4_header():
    """The worked IPv4 example whose published checksum is 0xB861."""
    header = bytes.fromhex("45000073000040004011" + "0000" + "c0a80001" + "c0a800c7")
    assert internet_checksum(header) == 0xB861


def test_checksum_in_place_verifies_to_zero():
    header = bytes.fromhex("45000073000040004011b861c0a80001c0a800c7")
    assert verify_checksum(header)
    assert internet_checksum(header) == 0


def test_checksum_detects_any_single_bit_error():
    header = bytes.fromhex("45000073000040004011b861c0a80001c0a800c7")
    for index in range(len(header) * 8):
        assert not verify_checksum(bits.flip_bit(header, index))


def test_checksum_steps_record_the_wraparound_carry():
    steps, total = checksum_steps(b"\xff\xff\x00\x01")
    assert any(step.carried for step in steps), "a carry must be reported"
    assert total == internet_checksum(b"\xff\xff\x00\x01")


def test_checksum_pads_odd_length():
    assert internet_checksum(b"\x12") == internet_checksum(b"\x12\x00")


# --------------------------------------------------------------------------
# CRC
# --------------------------------------------------------------------------


def test_crc32_matches_the_standard_check_value():
    """The published CRC-32 check value for the string "123456789"."""
    assert crc.crc32_ieee(b"123456789") == 0xCBF43926


@pytest.mark.parametrize("name", sorted(crc.GENERATORS))
def test_crc_codeword_divides_cleanly(name):
    generator = crc.generator_bits(name)
    data = bits.bytes_to_bits(b"NetLab")
    codeword, remainder, _ = crc.crc_encode(data, generator)

    assert len(remainder) == len(generator) - 1
    assert codeword[: len(data)] == data
    ok, received_remainder, _ = crc.crc_check(codeword, generator)
    assert ok and not any(received_remainder)


@pytest.mark.parametrize("name", sorted(crc.GENERATORS))
def test_crc_detects_every_single_bit_error(name):
    generator = crc.generator_bits(name)
    codeword, _, _ = crc.crc_encode(bits.bytes_to_bits(b"Hi"), generator)
    for index in range(len(codeword)):
        corrupted = list(codeword)
        corrupted[index] ^= 1
        assert not crc.crc_check(corrupted, generator)[0], f"missed bit {index}"


def test_crc_division_trace_covers_every_position():
    generator = crc.generator_bits("CRC-8")
    data = bits.bytes_to_bits(b"AB")
    padded = data + [0] * (len(generator) - 1)
    _, steps = crc.crc_remainder(padded, generator)
    assert len(steps) == len(padded) - len(generator) + 1
    assert all(step.divided == (step.dividend[0] == "1") for step in steps)


def test_crc_rejects_a_generator_not_starting_with_one():
    with pytest.raises(ValueError):
        crc.crc_remainder([1] * 16, [0, 1, 1])


# --------------------------------------------------------------------------
# Headers
# --------------------------------------------------------------------------


def test_ipv4_header_layout_and_checksum():
    view = network.build_ipv4(b"x" * 100, "10.0.0.1", "10.0.0.2", "TCP", ttl=64)
    assert len(view.header) == 20
    assert verify_checksum(view.header)

    parsed = network.parse_ipv4_header(view.header)
    assert parsed["version"] == 4
    assert parsed["ihl"] == 5
    assert parsed["total_length"] == 120  # 20 header + 100 payload
    assert parsed["ttl"] == 64
    assert parsed["protocol"] == 6
    assert parsed["src"] == "10.0.0.1"
    assert parsed["checksum_valid"]


def test_ipv4_total_length_tracks_the_payload():
    for size in (0, 1, 500):
        view = network.build_ipv4(b"x" * size, "10.0.0.1", "10.0.0.2")
        assert network.parse_ipv4_header(view.header)["total_length"] == 20 + size


def test_ipv6_header_is_forty_bytes_with_no_checksum():
    view = network.build_ipv6(b"x" * 64)
    assert len(view.header) == 40
    assert not any(item.name == "Header Checksum" for item in view.fields)
    # Payload Length counts the payload only, unlike IPv4's Total Length.
    assert struct.unpack("!H", view.header[4:6])[0] == 64


def test_tcp_header_and_pseudo_header_checksum():
    payload = b"GET / HTTP/1.1\r\n\r\n"
    view = transport.build_tcp(
        payload, "10.0.0.1", "10.0.0.2", 49152, 80, seq=1000, flags=["PSH", "ACK"]
    )
    assert len(view.header) == 20

    covered = (
        network.pseudo_header(
            bits.parse_ipv4("10.0.0.1"), bits.parse_ipv4("10.0.0.2"), 6, 20 + len(payload)
        )
        + view.header
        + payload
    )
    assert internet_checksum(covered) == 0

    src, dst, seq = struct.unpack("!HHI", view.header[:8])
    assert (src, dst, seq) == (49152, 80, 1000)


def test_tcp_flag_bits_land_in_the_right_places():
    view = transport.build_tcp(b"", "10.0.0.1", "10.0.0.2", 1, 2, flags=["SYN"])
    flags = struct.unpack("!H", view.header[12:14])[0] & 0x3F
    assert flags == 0b000010  # SYN is bit 1 of 6, counting from FIN
    named = {item.name: item.display for item in view.fields if item.name in transport.FLAGS}
    assert named["SYN"] == "1" and named["ACK"] == "0"


def test_tcp_checksum_covers_the_addresses():
    """Changing only the IP addresses must change the TCP checksum."""
    first = transport.build_tcp(b"data", "10.0.0.1", "10.0.0.2", 1, 2)
    second = transport.build_tcp(b"data", "10.0.0.9", "10.0.0.2", 1, 2)
    assert first.header[16:18] != second.header[16:18]


def test_udp_header_length_and_nonzero_checksum():
    payload = b"query"
    view = transport.build_udp(payload, "10.0.0.1", "10.0.0.2", 5000, 53)
    assert len(view.header) == 8
    assert struct.unpack("!H", view.header[4:6])[0] == 8 + len(payload)
    # Zero means "not computed" in UDP, so a real checksum is never sent as 0.
    assert struct.unpack("!H", view.header[6:8])[0] != 0


def test_ethernet_frame_check_sequence_verifies():
    view, padding = datalink.build_ethernet(b"x" * 100)
    frame = view.header + b"x" * 100 + padding + view.trailer
    assert datalink.verify_ethernet(frame)
    assert not datalink.verify_ethernet(bits.flip_bit(frame, 3))


def test_ethernet_pads_short_frames_to_the_minimum():
    view, padding = datalink.build_ethernet(b"hi")
    assert len(view.header) + 2 + len(padding) == datalink.ETHERNET_MIN_FRAME


def test_ethernet_fcs_is_little_endian():
    view, padding = datalink.build_ethernet(b"x" * 100)
    expected = crc.crc32_ieee(view.header + b"x" * 100 + padding)
    assert struct.unpack("<I", view.trailer)[0] == expected


# --------------------------------------------------------------------------
# Framing (syllabus 5.2)
# --------------------------------------------------------------------------


def test_byte_stuffing_roundtrip_with_flags_in_the_data():
    payload = bytes([0x7E, 0x41, 0x7D, 0x7E])
    stuffed = datalink.byte_stuff(payload)
    assert len(stuffed) == len(payload) + 3  # three bytes needed escaping
    assert datalink.byte_unstuff(stuffed) == payload


def test_bit_stuffing_breaks_every_run_of_five_ones():
    original = [1] * 12
    stuffed = datalink.bit_stuff(original)
    run = longest = 0
    for bit in stuffed:
        run = run + 1 if bit == 1 else 0
        longest = max(longest, run)
    assert longest <= 5
    assert datalink.bit_unstuff(stuffed) == original


# --------------------------------------------------------------------------
# DNS
# --------------------------------------------------------------------------


def test_qname_encoding_is_length_prefixed():
    assert application.encode_qname("www.example.com") == b"\x03www\x07example\x03com\x00"


def test_dns_query_structure():
    view, raw = application.build_dns_query("example.com", transaction_id=0x1234)
    assert raw[:2] == b"\x12\x34"
    assert struct.unpack("!H", raw[2:4])[0] == 0x0100  # recursion desired
    assert struct.unpack("!H", raw[4:6])[0] == 1  # one question
    assert raw[12:].startswith(b"\x07example\x03com\x00")


def test_dns_response_parsing_follows_compression_pointers():
    question = application.encode_qname("example.com") + struct.pack("!HH", 1, 1)
    answer = (
        b"\xc0\x0c"  # pointer back to the name at offset 12
        + struct.pack("!HHIH", 1, 1, 300, 4)
        + bytes([93, 184, 216, 34])
    )
    message = struct.pack("!HHHHHH", 0xABCD, 0x8180, 1, 1, 0, 0) + question + answer

    parsed = application.parse_dns_message(message)
    assert parsed["id"] == 0xABCD
    assert parsed["is_response"] and parsed["rcode"] == "NOERROR"
    assert parsed["questions"][0]["name"] == "example.com"
    assert parsed["answers"][0] == {
        "name": "example.com",
        "type": "A",
        "ttl": 300,
        "data": "93.184.216.34",
    }


def test_dns_rejects_a_circular_compression_pointer():
    message = struct.pack("!HHHHHH", 1, 0x8180, 1, 0, 0, 0) + b"\xc0\x0c"
    with pytest.raises(ValueError):
        application.parse_dns_message(message)


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


def test_assemble_lays_headers_then_payload_then_trailers():
    outer = LayerView("Data Link", "Eth", b"HH", trailer=b"TT", padding=b"P")
    inner = LayerView("Network", "IP", b"NNN")
    frame = assemble([outer, inner], b"data")

    assert frame.wire == b"HH" + b"NNN" + b"data" + b"P" + b"TT"
    assert (outer.header_start, outer.header_end) == (0, 2)
    assert (inner.header_start, inner.header_end) == (2, 5)
    assert frame.wire[inner.payload_start : inner.payload_end] == b"data"
    assert frame.wire[outer.trailer_start :] == b"TT"


def test_field_lookup_by_bit_finds_the_owning_field():
    frame = encapsulate(EncapsulationRequest())
    link = frame.layers[0]
    found = frame.field_at_bit(0)  # first bit of the destination MAC
    assert found is not None
    view, item = found
    assert view is link and item.name == "Destination MAC"


# --------------------------------------------------------------------------
# End-to-end encapsulation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "protocol,expected_transport", [("HTTP", "TCP"), ("DNS", "UDP"), ("SMTP", "TCP"), ("FTP", "TCP")]
)
def test_every_protocol_encapsulates_and_arrives(protocol, expected_transport):
    frame = encapsulate(EncapsulationRequest(app_protocol=protocol))
    assert frame.layers[2].protocol == expected_transport

    result = decapsulate(frame.wire, frame)
    assert result.delivered
    assert [check.ok for check in result.checks] == [True] * 4


def test_encapsulated_frame_is_self_consistent():
    frame = encapsulate(EncapsulationRequest())
    link, net, tran, app = frame.layers
    assert len(frame.wire) == (
        len(link.header) + len(net.header) + len(tran.header)
        + (app.payload_end - app.payload_start)
        + len(link.padding) + len(link.trailer)
    )
    assert datalink.verify_ethernet(frame.wire)
    assert verify_checksum(frame.wire[net.header_start : net.header_end])


def test_unknown_protocol_is_rejected():
    with pytest.raises(ValueError):
        encapsulate(EncapsulationRequest(app_protocol="GOPHER"))


# --------------------------------------------------------------------------
# Channel and failure attribution
# --------------------------------------------------------------------------


def test_wire_errors_are_caught_by_the_frame_check_sequence():
    frame = encapsulate(EncapsulationRequest())
    channel = Channel(ChannelConfig())
    for position in (22 * 8 + 3, 48 * 8 + 2, 60 * 8 + 1):
        received = channel.corrupt_at(frame.wire, [position])
        # On a real link the FCS covers everything, so it always catches first.
        assert decapsulate(received.received, frame).failed_at == "Data Link"


@pytest.mark.parametrize(
    "position,expected",
    [(22 * 8 + 3, "Network"), (48 * 8 + 2, "Transport"), (60 * 8 + 1, "Transport")],
)
def test_router_side_corruption_is_caught_by_the_end_to_end_checksums(position, expected):
    """With the FCS refreshed by a hop, only IP and TCP can still catch it."""
    frame = encapsulate(EncapsulationRequest())
    channel = Channel(ChannelConfig())
    received = channel.corrupt_at(frame.wire, [position], refresh_fcs=True)
    assert decapsulate(received.received, frame).failed_at == expected


def test_a_clean_channel_delivers_the_frame_untouched():
    frame = encapsulate(EncapsulationRequest())
    result = Channel(ChannelConfig(bit_error_rate=0.0)).transmit(frame.wire)
    assert result.delivered and not result.corrupted
    assert result.received == frame.wire


def test_total_loss_delivers_nothing():
    frame = encapsulate(EncapsulationRequest())
    result = Channel(ChannelConfig(loss_probability=1.0)).transmit(frame.wire)
    assert not result.delivered and result.received == b""


def test_delay_follows_size_over_bandwidth():
    frame = encapsulate(EncapsulationRequest())
    config = ChannelConfig(bandwidth_bps=1_000_000, distance_m=2.0e8)
    result = Channel(config).transmit(frame.wire)
    assert result.transmission_delay_ms == pytest.approx(len(frame.wire) * 8 / 1000)
    assert result.propagation_delay_ms == pytest.approx(1000.0)  # 2e8 m at 2e8 m/s


def test_seeding_makes_a_demo_repeatable():
    frame = encapsulate(EncapsulationRequest())
    config = ChannelConfig(bit_error_rate=0.01, seed=7)
    first = Channel(config).transmit(frame.wire)
    second = Channel(config).transmit(frame.wire)
    assert first.corrupted_bits == second.corrupted_bits


def test_channel_config_validates_its_inputs():
    with pytest.raises(ValueError):
        ChannelConfig(bit_error_rate=1.5)
    with pytest.raises(ValueError):
        ChannelConfig(bandwidth_bps=0)


# --------------------------------------------------------------------------
# pcap export
# --------------------------------------------------------------------------


def test_pcap_header_and_record_are_well_formed(tmp_path):
    frame = encapsulate(EncapsulationRequest())
    target = pcap.write_pcap(tmp_path / "out.pcap", [frame.wire])
    raw = target.read_bytes()

    magic, major, minor, _, _, snaplen, linktype = struct.unpack("<IHHiIII", raw[:24])
    assert magic == 0xA1B2C3D4
    assert (major, minor) == (2, 4)
    assert linktype == pcap.LINKTYPE_ETHERNET
    assert snaplen == 65535

    _, _, included, original = struct.unpack("<IIII", raw[24:40])
    # The FCS is stripped, matching what a real NIC hands the capture driver.
    assert included == original == len(frame.wire) - 4
    assert raw[40:] == frame.wire[:-4]


def test_pcap_writes_every_frame(tmp_path):
    frame = encapsulate(EncapsulationRequest())
    target = pcap.write_pcap(tmp_path / "multi.pcap", [frame.wire] * 3)
    size = target.stat().st_size
    assert size == 24 + 3 * (16 + len(frame.wire) - 4)

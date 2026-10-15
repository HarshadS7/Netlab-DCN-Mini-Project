"""Tests for the lab engines: Hamming, ARQ, addressing, routing and signals."""

from __future__ import annotations

import math

import pytest

from netlab.core import bits as bitlib
from netlab.core.arq.machines import PROTOCOLS, ArqConfig, go_back_n, selective_repeat, stop_and_wait
from netlab.core.errors import hamming
from netlab.core.layers.application import parse_dns_message
from netlab.core.live.stub_resolver import StubResolver
from netlab.core.routing import addressing as ad
from netlab.core.routing.algorithms import (
    Topology,
    count_to_infinity,
    dijkstra,
    distance_vector,
    path_between,
    routing_table,
)
from netlab.core.signals import line_coding as lc
from netlab.core.signals import modulation as mod
from netlab.core.transport_sim import (
    CongestionConfig,
    congestion_trace,
    handshake,
    sliding_window,
    teardown,
)


# --------------------------------------------------------------------------
# Hamming
# --------------------------------------------------------------------------


def test_hamming_74_matches_the_textbook_example():
    """Data 1011 encodes to 0110011 with parity at positions 1, 2 and 4."""
    code = hamming.encode([1, 0, 1, 1])
    assert code.n == 7 and code.k == 4
    assert code.codeword == [0, 1, 1, 0, 0, 1, 1]
    assert [parity.position for parity in code.parity] == [1, 2, 4]
    assert code.parity[0].covers == [1, 3, 5, 7]
    assert code.parity[1].covers == [2, 3, 6, 7]
    assert code.parity[2].covers == [4, 5, 6, 7]


@pytest.mark.parametrize("length", range(1, 12))
def test_hamming_corrects_every_single_bit_error(length):
    data = [(index * 7 + 3) % 2 for index in range(length)]
    code = hamming.encode(data)

    assert not hamming.decode(code.codeword).error_found

    for position in range(1, code.n + 1):
        corrupted = list(code.codeword)
        corrupted[position - 1] ^= 1
        result = hamming.decode(corrupted)
        assert result.error_position == position, f"syndrome named {result.syndrome}"
        assert result.corrected == code.codeword
        assert result.data_bits == data


def test_hamming_redundancy_satisfies_the_inequality():
    for length in range(1, 30):
        r = hamming.redundant_bits_needed(length)
        assert 2**r >= length + r + 1
        assert 2 ** (r - 1) < length + (r - 1) + 1  # and it is the smallest such r


def test_hamming_cannot_fix_two_bit_errors():
    """A double error is mis-corrected. That is the code's real limitation."""
    code = hamming.encode([1, 0, 1, 1])
    corrupted = list(code.codeword)
    corrupted[2] ^= 1
    corrupted[5] ^= 1
    result = hamming.decode(corrupted)
    assert result.corrected != code.codeword


def test_hamming_rejects_empty_input():
    with pytest.raises(ValueError):
        hamming.encode([])


# --------------------------------------------------------------------------
# ARQ
# --------------------------------------------------------------------------


@pytest.mark.parametrize("protocol", list(PROTOCOLS))
def test_every_protocol_delivers_all_frames_in_order(protocol):
    config = ArqConfig(total_frames=6, window=4, lose_data={2})
    result = PROTOCOLS[protocol](config)
    assert result.delivered == list(range(6))


def test_go_back_n_resends_more_than_selective_repeat():
    """The defining difference: one loss costs GBN the whole window."""
    config = lambda: ArqConfig(total_frames=6, window=4, lose_data={2})
    gbn = go_back_n(config())
    sr = selective_repeat(config())
    assert gbn.transmissions > sr.transmissions
    assert gbn.efficiency < sr.efficiency

    # Go-Back-N discards the in-order frames that arrived after the loss.
    assert any(arrow.discarded for arrow in gbn.arrows)
    assert not any(arrow.discarded for arrow in sr.arrows)


def test_selective_repeat_resends_only_the_lost_frame():
    result = selective_repeat(ArqConfig(total_frames=6, window=4, lose_data={2}))
    sent = [arrow.seq for arrow in result.arrows if arrow.kind == "data"]
    assert sent.count(2) == 2  # lost once, resent once
    assert all(sent.count(seq) == 1 for seq in (0, 1, 3, 4, 5))


def test_stop_and_wait_keeps_one_frame_in_flight():
    result = stop_and_wait(ArqConfig(total_frames=4))
    data = [arrow for arrow in result.arrows if arrow.kind == "data"]
    for first, second in zip(data, data[1:]):
        assert second.start >= first.end - 1e-9, "a second frame went out too early"


def test_a_clean_channel_needs_no_retransmissions():
    for run in PROTOCOLS.values():
        result = run(ArqConfig(total_frames=5, window=3))
        assert result.transmissions == 5
        assert result.efficiency == pytest.approx(100.0)


def test_lost_acknowledgement_triggers_a_timeout():
    result = stop_and_wait(ArqConfig(total_frames=3, lose_acks={1}))
    assert result.timeouts
    assert result.delivered == [0, 1, 2]


# --------------------------------------------------------------------------
# Addressing
# --------------------------------------------------------------------------


def test_split_192_168_1_0_24_into_four():
    subnets = ad.split_equally(ad.parse_cidr("192.168.1.0/24"), 4)
    assert [subnet.cidr for subnet in subnets] == [
        "192.168.1.0/26",
        "192.168.1.64/26",
        "192.168.1.128/26",
        "192.168.1.192/26",
    ]
    assert all(subnet.usable_hosts == 62 for subnet in subnets)
    assert [ad.to_dotted(subnet.broadcast) for subnet in subnets] == [
        "192.168.1.63",
        "192.168.1.127",
        "192.168.1.191",
        "192.168.1.255",
    ]


def test_prefix_edge_cases():
    """/31 and /32 break the usual "minus two" rule."""
    assert ad.parse_cidr("10.0.0.0/31").usable_hosts == 2  # RFC 3021 point-to-point
    assert ad.parse_cidr("10.0.0.1/32").usable_hosts == 1
    assert ad.parse_cidr("10.0.0.0/24").usable_hosts == 254


def test_parse_cidr_snaps_to_the_network_address():
    assert ad.parse_cidr("192.168.1.77/24").cidr == "192.168.1.0/24"


def test_vlsm_allocates_largest_first_and_stays_aligned():
    allocations = ad.vlsm(
        ad.parse_cidr("172.16.0.0/22"),
        [("Sales", 500), ("Eng", 200), ("Lab", 50), ("WAN", 2)],
    )
    assert [allocation.name for allocation in allocations] == ["Sales", "Eng", "Lab", "WAN"]
    assert [allocation.subnet.cidr for allocation in allocations] == [
        "172.16.0.0/23",
        "172.16.2.0/24",
        "172.16.3.0/26",
        "172.16.3.64/30",
    ]
    for allocation in allocations:
        assert allocation.subnet.usable_hosts >= allocation.requested
        # Every block starts on a boundary matching its own size.
        assert allocation.subnet.network % allocation.subnet.total_addresses == 0


def test_vlsm_reports_when_it_will_not_fit():
    with pytest.raises(ValueError):
        ad.vlsm(ad.parse_cidr("192.168.1.0/24"), [("A", 200), ("B", 200)])


def test_longest_prefix_match_prefers_specificity_over_order():
    routes = [
        ad.Route(ad.parse_cidr("0.0.0.0/0"), "ISP"),
        ad.Route(ad.parse_cidr("10.0.0.0/8"), "R2"),
        ad.Route(ad.parse_cidr("10.1.0.0/16"), "R3"),
        ad.Route(ad.parse_cidr("10.1.2.0/24"), "R4"),
    ]
    assert ad.longest_prefix_match(routes, "10.1.2.7").next_hop == "R4"
    assert ad.longest_prefix_match(routes, "10.1.9.1").next_hop == "R3"
    assert ad.longest_prefix_match(routes, "10.9.0.1").next_hop == "R2"
    assert ad.longest_prefix_match(routes, "8.8.8.8").next_hop == "ISP"

    # Reversing the table must not change the answer.
    assert ad.longest_prefix_match(list(reversed(routes)), "10.1.2.7").next_hop == "R4"


# --------------------------------------------------------------------------
# Routing algorithms
# --------------------------------------------------------------------------


def sample_topology() -> Topology:
    topology = Topology()
    for name in "ABCDE":
        topology.add_node(name)
    for a, b, cost in [
        ("A", "B", 4),
        ("A", "C", 2),
        ("B", "C", 1),
        ("B", "D", 5),
        ("C", "D", 8),
        ("D", "E", 6),
        ("C", "E", 10),
    ]:
        topology.add_link(a, b, cost)
    return topology


def test_dijkstra_matches_the_hand_computed_graph():
    final = dijkstra(sample_topology(), "A")[-1]
    assert final.distance == {"A": 0, "B": 3, "C": 2, "D": 8, "E": 12}
    assert path_between(final.previous, "A", "D") == ["A", "C", "B", "D"]
    assert path_between(final.previous, "A", "E") == ["A", "C", "E"]


def test_dijkstra_settles_every_node_once():
    steps = dijkstra(sample_topology(), "A")
    settled = [step.settled for step in steps[1:]]
    assert sorted(settled) == list("ABCDE")


def test_routing_table_next_hops():
    table = dict((row[0], row[1]) for row in routing_table(sample_topology(), "A"))
    assert table == {"B": "C", "C": "C", "D": "C", "E": "C"}


def test_distance_vector_agrees_with_dijkstra():
    topology = sample_topology()
    optimal = dijkstra(topology, "A")[-1].distance
    converged = distance_vector(topology)[-1].tables["A"]
    for node, cost in optimal.items():
        assert converged[node][0] == cost


def test_distance_vector_converges_and_reports_it():
    rounds = distance_vector(sample_topology())
    assert rounds[-1].converged
    assert not rounds[-1].changed


def test_count_to_infinity_climbs_then_hits_the_ceiling():
    """Without split horizon the estimate must actually count upward."""
    topology = Topology()
    for name in "XYZ":
        topology.add_node(name)
    topology.add_link("X", "Y", 1)
    topology.add_link("Y", "Z", 1)

    history = count_to_infinity(topology, ("Y", "Z"))
    costs = [
        entry.tables["X"]["Z"][0] for entry in history if "Z" in entry.tables["X"]
    ]
    assert max(costs) > 2, "the estimate never rose, so no loop was demonstrated"
    assert max(costs) < 16, "RIP's ceiling should stop it before infinity"
    # It must eventually give up entirely.
    assert "Z" not in history[-1].tables["X"]


def test_split_horizon_prevents_the_two_node_loop():
    def chain() -> Topology:
        topology = Topology()
        for name in "XYZ":
            topology.add_node(name)
        topology.add_link("X", "Y", 1)
        topology.add_link("Y", "Z", 1)
        return topology

    without = count_to_infinity(chain(), ("Y", "Z"))
    with_horizon = count_to_infinity(chain(), ("Y", "Z"), split_horizon=True)
    assert len(with_horizon) < len(without)


def test_removing_a_link_reports_whether_it_existed():
    topology = sample_topology()
    assert topology.remove_link("A", "B")
    assert not topology.remove_link("A", "B")
    assert topology.cost("A", "B") == math.inf


# --------------------------------------------------------------------------
# Signals
# --------------------------------------------------------------------------


@pytest.mark.parametrize("scheme", list(lc.SCHEMES))
def test_every_line_code_produces_a_waveform(scheme):
    waveform = lc.encode(scheme, [0, 1, 1, 0, 1])
    assert waveform.times and waveform.levels
    assert len(waveform.times) == len(waveform.levels)
    assert all(-1.0 <= level <= 1.0 for level in waveform.levels)


def test_manchester_transitions_inside_every_bit():
    bits = [0, 0, 0, 1, 1, 1]
    waveform = lc.encode("Manchester", bits)
    for index in range(len(bits)):
        first, second = waveform.levels[index * 4], waveform.levels[index * 4 + 2]
        assert first != second, f"bit {index} has no mid-bit transition"


def test_nrz_l_level_follows_the_bit():
    waveform = lc.encode("NRZ-L", [0, 1])
    assert waveform.levels[0] == -1.0
    assert waveform.levels[2] == 1.0


def test_ami_alternates_polarity_and_averages_to_zero():
    waveform = lc.encode("AMI", [1, 0, 1, 0, 1, 1])
    marks = [level for level in waveform.levels[::2] if level != 0.0]
    for first, second in zip(marks, marks[1:]):
        assert first != second, "two consecutive marks had the same polarity"


def test_b8zs_inserts_two_violations_for_eight_zeros():
    waveform = lc.encode("B8ZS", [1] + [0] * 8 + [1])
    assert len(waveform.violations) == 2


def test_hdb3_substitutes_after_four_zeros():
    plain = lc.encode("HDB3", [1, 0, 1, 0, 1])
    assert not plain.violations
    substituted = lc.encode("HDB3", [1] + [0] * 4 + [1])
    assert substituted.violations


def test_nyquist_and_shannon_match_the_formulas():
    assert mod.nyquist_rate(3000, 2) == 6000
    assert mod.nyquist_rate(3000, 4) == 12000
    assert mod.shannon_capacity(3000, 30) == pytest.approx(29901.44, abs=1.0)
    # Shannon does not care how many levels you use.
    assert mod.shannon_capacity(3000, 30) == mod.shannon_capacity(3000, 30)


def test_nyquist_rejects_one_level():
    with pytest.raises(ValueError):
        mod.nyquist_rate(3000, 1)


def test_qpsk_carries_two_bits_per_symbol():
    result = mod.modulate("QPSK", [0, 1, 1, 0, 1, 1])
    assert result.bits_per_symbol == 2
    assert result.baud == 3
    assert len(result.constellation) == 4


def test_pcm_quantisation_error_stays_within_half_a_step():
    result = mod.pcm(frequency=1.0, sample_rate=16.0, levels=16, amplitude=1.0)
    step = 2.0 / 16
    assert all(abs(error) <= step / 2 + 1e-9 for error in result.error)
    assert result.bit_rate == 16.0 * 4


def test_pcm_code_width_follows_the_level_count():
    assert mod.pcm(levels=8).bits_per_sample == 3
    assert mod.pcm(levels=16).bits_per_sample == 4


def test_fdm_inserts_guard_bands():
    bands = mod.fdm(["A", "B", "C"], total_bandwidth=12.0, guard=1.0)
    assert len(bands) == 3
    for (_, _, end), (_, start, _) in zip(bands, bands[1:]):
        assert start - end == pytest.approx(1.0)


# --------------------------------------------------------------------------
# Transport mechanics
# --------------------------------------------------------------------------


def test_handshake_is_three_segments_ending_established():
    events = handshake()
    assert len(events) == 3
    assert events[-1].client_state == events[-1].server_state == "ESTABLISHED"
    assert events[0].flags == ["SYN"]
    assert events[1].flags == ["SYN", "ACK"]
    # The server acknowledges the client's ISN plus one: SYN consumes a number.
    assert events[1].ack == events[0].seq + 1


def test_teardown_is_four_segments_and_passes_through_time_wait():
    events = teardown()
    assert len(events) == 4
    assert any(event.server_state == "CLOSE_WAIT" for event in events)
    assert any(event.client_state == "TIME_WAIT" for event in events)
    assert events[-1].server_state == "CLOSED"


def test_slow_start_is_exponential_then_linear():
    trace = congestion_trace(
        CongestionConfig(rounds=12, initial_ssthresh=8, triple_dup_rounds=set(), timeout_rounds=set())
    )
    cwnd = [point.cwnd for point in trace]
    assert cwnd[:4] == [1, 2, 4, 8]  # doubling below ssthresh
    assert cwnd[4:7] == [9, 10, 11]  # +1 per round after it


def test_triple_duplicate_ack_halves_without_slow_start():
    trace = congestion_trace(
        CongestionConfig(rounds=20, initial_ssthresh=32, triple_dup_rounds={6}, timeout_rounds=set())
    )
    before, at = trace[5].cwnd, trace[6].cwnd
    # Fast recovery sets cwnd to the new ssthresh, which is half the window
    # that was in use. The trace records cwnd before advancing it, so allow a
    # segment of slack rather than pinning an exact figure.
    assert at == trace[6].ssthresh
    assert at == pytest.approx(before / 2, abs=1.0)
    assert at > 1, "fast recovery must not collapse the window to one"
    assert trace[6].phase == "fast recovery"


def test_timeout_collapses_the_window_to_one():
    trace = congestion_trace(
        CongestionConfig(rounds=20, initial_ssthresh=32, triple_dup_rounds=set(), timeout_rounds={6})
    )
    assert trace[6].cwnd == 1
    assert trace[6].phase == "slow start"


def test_sliding_window_never_exceeds_its_size():
    frames = sliding_window(total=10, window=4)
    for frame in frames:
        assert len(frame.in_flight) <= frame.window
    assert frames[-1].base == 10


# --------------------------------------------------------------------------
# The offline resolver
# --------------------------------------------------------------------------


def test_stub_resolver_answers_a_real_query():
    from netlab.core.layers.application import build_dns_query

    _, query = build_dns_query("example.com", "A", transaction_id=0x4242)
    reply = StubResolver.build_reply(query)
    parsed = parse_dns_message(reply)

    assert parsed["id"] == 0x4242
    assert parsed["is_response"]
    assert parsed["rcode"] == "NOERROR"
    assert parsed["answers"][0]["data"] == "93.184.216.34"
    # It uses a compression pointer, exactly as a real server would.
    assert b"\xc0\x0c" in reply


def test_stub_resolver_returns_nxdomain_for_unknown_names():
    from netlab.core.layers.application import build_dns_query

    _, query = build_dns_query("nothing.invalid", "A")
    parsed = parse_dns_message(StubResolver.build_reply(query))
    assert parsed["rcode"] == "NXDOMAIN"
    assert parsed["answers"] == []


def test_stub_resolver_binds_a_real_socket():
    with StubResolver() as stub:
        assert stub.host == "127.0.0.1"
        assert stub.port > 0

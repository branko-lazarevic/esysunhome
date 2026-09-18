"""Partial frames must never invent measurements or operating modes."""
from datetime import datetime, UTC
import logging
import struct

import pytest

from .test_threephase_decode import protocol
from esyx.protocol_api import ProtocolDefinition, RegisterDefinition


def make_parser(tp_type=1):
    definition = ProtocolDefinition(1, 6000, tp_type, 1, fetched_at=datetime.now(UTC))
    keys = {
        5: "systemRunMode", 6: "systemRunStatus", 28: "batteryStatus",
        29: "batteryPower", 32: "battTotalSoc", 40: "ct1Power",
        41: "loadRealTimePower", 50: "pv1Power", 51: "pv2Power",
        52: "ct2Power",
    }
    for address, key in keys.items():
        definition.input_registers[address] = RegisterDefinition(
            address, key, "signed", 1, "", 2, 4
        )
    parser = protocol.DynamicTelemetryParser(definition)
    parser.set_tp_type(tp_type)
    return parser


def segment(address, *values, count=None):
    return struct.pack(">HHHH", 0, 4, address, len(values) if count is None else count) + b"".join(
        struct.pack(">H", value & 0xffff) for value in values
    )


def frame(*segments, count=None):
    payload = struct.pack(">H", len(segments) if count is None else count) + b"".join(segments)
    return protocol.MsgHeader(1, 1, bytes(8), 3, 0, 0, len(payload)).to_bytes() + payload


@pytest.mark.parametrize("packet", [b"", b"short", frame(), frame(segment(5, count=1)), frame(b"\x00", count=1), frame(segment(999, 1))])
def test_no_usable_registers_produce_no_update(packet):
    assert make_parser().parse_message(packet) is None


def test_two_valid_segments_before_truncated_third_only_update_present_values(caplog):
    packet = frame(segment(28, 5, 6100), segment(6, 2), segment(5, *([1] * 101), count=821))
    with caplog.at_level(logging.DEBUG):
        result = make_parser().parse_message(packet)
    assert result["batteryPower"] == 6100
    assert result["batteryExport"] == 6100
    assert result["systemRunStatus"] == 2
    assert "code" not in result
    assert "systemRunMode" not in result
    for key in ("gridPower", "pvPower", "loadPower", "batterySoc", "gridFrequency"):
        assert key not in result
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert "1642" in caplog.text
    assert "have 202" in caplog.text
    assert "params_num=821" in caplog.text
    assert "seg_addr=5" in caplog.text
    assert "hex=" in caplog.text


@pytest.mark.parametrize("tp_type", [1, 3])
@pytest.mark.parametrize("values,absent", [
    ({}, {"pvPower", "gridPower", "batteryPower", "loadPower", "code", "batterySoc"}),
    ({"systemRunStatus": 2}, {"systemRunMode", "code", "patternMode"}),
    ({"batteryStatus": 5}, {"batteryPower", "batteryImport", "batteryExport"}),
    ({"batteryPower": 100}, {"batteryStatus", "batteryImport", "batteryExport", "batteryStatusText"}),
    ({"pv1Power": 0}, {"pv2Power", "acPvPower", "dcPvPower", "pvPower"}),
    ({"ct2Power": 100}, {"gridPower", "pv1Power", "pv2Power", "pvPower"}),
    ({"phaseAgridActivePower": -100}, {"gridPower", "gridImport", "gridExport"}),
    ({"loadRealTimePower": 500, "totalPowerOfGridInFlow": 800}, {"pvPower", "batteryPower", "batteryImport", "batteryExport"}),
])
def test_incomplete_dependencies_never_synthesize_values(tp_type, values, absent):
    result = make_parser(tp_type)._compute_derived_values(values)
    assert absent.isdisjoint(result)


def test_zero_mode_and_soc_are_real_readings():
    result = make_parser()._compute_derived_values({"systemRunMode": 0, "battTotalSoc": 0, "batterySoc": 40})
    assert result["code"] == "Battery Priority Mode"
    assert result["batterySoc"] == 0
    assert "systemRunStatus" not in result


def test_invalid_soc_is_omitted_not_zeroed():
    result = make_parser()._compute_derived_values({"battTotalSoc": 65535, "batterySoc": 65535})
    assert "batterySoc" not in result


def test_real_zero_measurements_are_published():
    result = make_parser().parse_message(frame(segment(28, 0, 0), segment(40, 0, 0), segment(50, 0, 0, 0)))
    for key in ("pvPower", "gridPower", "batteryPower", "loadPower", "batteryImport", "batteryExport"):
        assert result[key] == 0


def test_three_phase_single_ct_does_not_become_whole_site_grid():
    result = make_parser(3).parse_message(frame(segment(40, -100)))
    assert "gridPower" not in result


def test_three_phase_small_inflow_is_not_replaced_with_default_zero():
    result = make_parser(3)._compute_derived_values({"totalPowerOfGridInFlow": 5})
    assert result["gridPower"] == 5


def test_truncated_header_diagnostics_are_debug(caplog):
    with caplog.at_level(logging.DEBUG):
        assert make_parser().parse_message(frame(b"\x00\x01\x00", count=1)) is None
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert "hex=" in caplog.text


def test_every_truncation_boundary_preserves_only_complete_segments():
    parser = make_parser()
    packet = frame(segment(28, 5, 6100), segment(6, 2), segment(5, 3))
    for end in range(len(packet) + 1):
        result = parser.parse_message(packet[:end])
        if end < 38:  # 24-byte header + count + first 8+4-byte segment
            assert result is None
            continue
        assert result["batteryPower"] == 6100
        assert result["batteryExport"] == 6100
        assert "gridPower" not in result
        if end < 48:
            assert "systemRunStatus" not in result
        if end < 58:
            assert "code" not in result
        else:
            assert result["code"] == "Electricity Sell Mode"


def test_protocol_without_second_pv_input_can_compute_total():
    parser = make_parser()
    del parser.protocol.input_registers[51]
    del parser.protocol.input_registers[52]
    result = parser.parse_message(frame(segment(50, 3000)))
    assert result["pvPower"] == 3000
    assert result["dcPvPower"] == 3000
    assert "pv2Power" not in result
    assert "acPvPower" not in result


def test_complete_three_phase_sum_includes_all_phases():
    result = make_parser(3)._compute_derived_values({
        "phaseAgridActivePower": -100,
        "phaseBgridActivePower": -200,
        "phaseCgridActivePower": -300,
    })
    assert result["gridPower"] == 600
    assert result["gridImport"] == 600


@pytest.mark.parametrize("key", ["pv1Power", "batterySoc", "batteryPower", "systemRunMode", "loadPower"])
def test_none_measurements_are_absent(key):
    assert make_parser()._compute_derived_values({key: None}) == {}

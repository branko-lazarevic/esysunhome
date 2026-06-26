"""Regression tests for the 3-phase telemetry decode corrections.

These mirror the fixes ported from the solaniq_optimizer ESY adapter:
  * exclude the single-phase ct1Power CT clamp on 3-phase sites,
  * treat totalPowerOfGridInFlow as +import (do NOT flip its sign),
  * prefer the AC-side energyFlowBattPower over the DC batteryPower register,
  * prefer the inverter energyFlowLoadTotalPower figure for load,
  * normalise the 3-phase per-source flows to conserve with load
    (EnergyFlowOptimize), with a guard so a missing load can't zero the flows.

protocol.py is loaded via a synthetic package so its relative imports resolve
without importing Home Assistant (the real package __init__ pulls in HA).
"""

import importlib
import pathlib
import sys
import types

_PKG_DIR = (
    pathlib.Path(__file__).resolve().parent.parent
    / "custom_components" / "esy_sunhome"
)
if "esyx" not in sys.modules:
    _pkg = types.ModuleType("esyx")
    _pkg.__path__ = [str(_PKG_DIR)]
    sys.modules["esyx"] = _pkg
protocol = importlib.import_module("esyx.protocol")


def _decode(tp_type, values):
    parser = protocol.DynamicTelemetryParser(protocol=None)
    parser.set_tp_type(tp_type)
    return parser._compute_derived_values(dict(values))


def test_single_phase_grid_sign_unchanged():
    # ESY raw ct1Power negative = import; HA convention flips to +import.
    r = _decode(1, {"ct1Power": -150, "loadRealTimePower": 500, "batteryStatus": 0})
    assert r["gridPower"] == 150
    assert r["gridImport"] == 150 and r["gridExport"] == 0

    r = _decode(1, {"ct1Power": 200, "batteryStatus": 0})
    assert r["gridPower"] == -200 and r["gridExport"] == 200


def test_three_phase_inflow_is_import_and_ct1_excluded():
    # Balanced frame so the conservation step is a no-op and we isolate
    # source selection + sign: totalPowerOfGridInFlow is already +import, and
    # the single-phase ct1Power clamp must be ignored.
    r = _decode(3, {
        "totalPowerOfGridInFlow": 800,
        "ct1Power": -50,
        "energyFlowLoadTotalPower": 800,
        "batteryStatus": 0,
    })
    assert r["gridPower"] == 800 and r["gridImport"] == 800
    assert r["loadPower"] == 800


def test_battery_prefers_ac_energy_flow_over_dc_register():
    r = _decode(1, {
        "energyFlowBattPower": 2200,
        "batteryPower": 2600,
        "batteryStatus": 5,  # discharging
        "loadRealTimePower": 2200,
    })
    assert r["batteryPower"] == 2200
    assert r["batteryExport"] == 2200  # discharge = export from battery


def test_three_phase_flows_conserve_with_load():
    # pv gen 3000, grid export 900, battery charge 2000, measured load 50.
    r = _decode(3, {
        "pv1Power": 3000,
        "totalPowerOfGridInFlow": -900,
        "energyFlowBattPower": -2000,
        "batteryStatus": 1,  # charging
        "energyFlowLoadTotalPower": 50,
    })
    signed_batt = r["batteryExport"] - r["batteryImport"]
    total = r["pvPower"] + r["gridPower"] + signed_batt
    # Exact up to <=1W independent-rounding of the three flows.
    assert abs(total - r["loadPower"]) <= 1


def test_three_phase_missing_load_does_not_zero_flows():
    r = _decode(3, {
        "pv1Power": 3000,
        "totalPowerOfGridInFlow": -900,
        "energyFlowBattPower": -2000,
        "batteryStatus": 1,
    })
    assert r["pvPower"] == 3000
    assert r["gridPower"] == -900

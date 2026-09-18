"""Exercise real coordinator/entity reporting without connecting to the inverter."""
import importlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esy_sunhome.coordinator import ESYSunhomeCoordinator, TelemetryData
from custom_components.esy_sunhome.select import ModeSelect
from custom_components.esy_sunhome.sensor import BatteryPowerSensor, GridPowerSensor, LoadPowerSensor
from .test_partial_telemetry import make_parser, frame, segment


@pytest.fixture
def coordinator(hass):
    entry = MockConfigEntry(domain="esy_sunhome", data={"device_id": "test-device"})
    entry.add_to_hass(hass)
    result = ESYSunhomeCoordinator(hass, SimpleNamespace(device_id="test-device"), "test-sn", entry)
    result.parser = make_parser()
    return result


def test_select_starts_unknown(coordinator):
    entity = ModeSelect(coordinator, coordinator.config_entry)
    assert entity.current_option is None


async def test_partial_frames_preserve_sensor_and_select_state(coordinator):
    mode = ModeSelect(coordinator, coordinator.config_entry)
    sensors = [BatteryPowerSensor(coordinator), GridPowerSensor(coordinator), LoadPowerSensor(coordinator)]
    for entity in [mode, *sensors]:
        # Only HA state-machine publication is replaced; decoding, merging and
        # the entity callbacks are real. No MQTT/API write method is called.
        entity.async_write_ha_state = Mock()

    await coordinator._process_telemetry(frame(segment(5, 3), segment(28, 5, 6100), segment(40, 4900, 1200)))
    for entity in [mode, *sensors]:
        entity._handle_coordinator_update()
    assert mode.current_option == "Electricity Sell Mode"
    assert [s.native_value for s in sensors] == [6100, -4900, 1200]
    for packet in [frame(segment(32, 70), segment(6, 2), segment(5, 1, count=821)), b"short", frame()]:
        await coordinator._process_telemetry(packet)
        for entity in [mode, *sensors]:
            entity._handle_coordinator_update()
        assert mode.current_option == "Electricity Sell Mode"
        assert [s.native_value for s in sensors] == [6100, -4900, 1200]
    await coordinator._process_telemetry(frame(segment(5, 4), segment(28, 0, 0), segment(40, 0, 0)))
    for entity in [mode, *sensors]:
        entity._handle_coordinator_update()
    assert mode.current_option == "Emergency Mode"
    assert [s.native_value for s in sensors] == [0, 0, 0]


def test_missing_mode_keeps_last_option_and_publishes_availability(coordinator):
    mode = ModeSelect(coordinator, coordinator.config_entry)
    mode.async_write_ha_state = Mock()
    coordinator.data = TelemetryData({"code": "Emergency Mode"})
    mode._handle_coordinator_update()
    coordinator.data = TelemetryData({"batterySoc": 50})
    mode._handle_coordinator_update()
    assert mode.current_option == "Emergency Mode"
    assert mode.async_write_ha_state.call_count == 2


async def test_diagnostics_can_be_loaded_in_executor(hass):
    # The upstream runtime import references a non-existent coordinator class.
    module = await hass.async_add_executor_job(importlib.import_module, "custom_components.esy_sunhome.diagnostics")
    assert callable(module.async_get_config_entry_diagnostics)


async def test_diagnostics_exports_telemetry_after_preload(hass, coordinator):
    import sys
    from custom_components.esy_sunhome import _preimport_modules

    await hass.async_add_executor_job(_preimport_modules)
    module = sys.modules["custom_components.esy_sunhome.diagnostics"]
    coordinator.data = TelemetryData({"batterySoc": 70, "code": "Emergency Mode"})
    coordinator.config_entry.runtime_data = coordinator
    result = await module.async_get_config_entry_diagnostics(hass, coordinator.config_entry)
    assert result["parsed_values"]["batterySoc"] == 70
    assert result["parsed_values"]["code"] == "Emergency Mode"

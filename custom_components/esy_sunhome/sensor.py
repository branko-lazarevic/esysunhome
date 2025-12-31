"""ESY Sunhome sensor platform."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import EsySunhomeEntity
from .const import (
    ATTR_SOC,
    ATTR_GRID_POWER,
    ATTR_LOAD_POWER,
    ATTR_BATTERY_POWER,
    ATTR_PV_POWER,
    ATTR_BATTERY_IMPORT,
    ATTR_BATTERY_EXPORT,
    ATTR_GRID_IMPORT,
    ATTR_GRID_EXPORT,
    ATTR_DAILY_POWER_GEN,
    ATTR_RATED_POWER,
    ATTR_INVERTER_TEMP,
    ATTR_BATTERY_STATUS_TEXT,
    ATTR_PV1_POWER,
    ATTR_PV2_POWER,
    ATTR_PV1_VOLTAGE,
    ATTR_PV1_CURRENT,
    ATTR_PV2_VOLTAGE,
    ATTR_PV2_CURRENT,
    ATTR_BATTERY_VOLTAGE,
    ATTR_BATTERY_CURRENT,
    ATTR_GRID_VOLTAGE,
    ATTR_GRID_FREQUENCY,
    ATTR_INV_OUTPUT_VOLTAGE,
    ATTR_INV_OUTPUT_FREQUENCY,
    ATTR_TOTAL_ENERGY_GEN,
    ATTR_DAILY_POWER_CONSUMPTION,
    ATTR_TOTAL_POWER_CONSUMPTION,
    ATTR_DAILY_BATT_CHARGE,
    ATTR_DAILY_BATT_DISCHARGE,
    ATTR_DAILY_GRID_IMPORT_ENERGY,
    ATTR_DAILY_GRID_EXPORT_ENERGY,
    ATTR_SYSTEM_RUN_MODE,
    ATTR_CT1_POWER,
    ATTR_CT2_POWER,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator = entry.runtime_data

    entities = [
        # Existing sensors (backwards compatible)
        StateOfChargeSensor(coordinator=coordinator),
        GridPowerSensor(coordinator=coordinator),
        LoadPowerSensor(coordinator=coordinator),
        BatteryPowerSensor(coordinator=coordinator),
        PvPowerSensor(coordinator=coordinator),
        BatteryImportSensor(coordinator=coordinator),
        BatteryExportSensor(coordinator=coordinator),
        GridImportSensor(coordinator=coordinator),
        GridExportSensor(coordinator=coordinator),
        DailyPowerGenSensor(coordinator=coordinator),
        RatedPowerSensor(coordinator=coordinator),
        BatteryStatusTextSensor(coordinator=coordinator),
        InverterTempSensor(coordinator=coordinator),
        # New v2.0.0 sensors
        Pv1PowerSensor(coordinator=coordinator),
        Pv2PowerSensor(coordinator=coordinator),
        Pv1VoltageSensor(coordinator=coordinator),
        Pv1CurrentSensor(coordinator=coordinator),
        Pv2VoltageSensor(coordinator=coordinator),
        Pv2CurrentSensor(coordinator=coordinator),
        BatteryVoltageSensor(coordinator=coordinator),
        BatteryCurrentSensor(coordinator=coordinator),
        GridVoltageSensor(coordinator=coordinator),
        GridFrequencySensor(coordinator=coordinator),
        InvOutputVoltageSensor(coordinator=coordinator),
        InvOutputFrequencySensor(coordinator=coordinator),
        TotalEnergyGenSensor(coordinator=coordinator),
        DailyPowerConsumptionSensor(coordinator=coordinator),
        TotalPowerConsumptionSensor(coordinator=coordinator),
        DailyBattChargeSensor(coordinator=coordinator),
        DailyBattDischargeSensor(coordinator=coordinator),
        DailyGridImportEnergySensor(coordinator=coordinator),
        DailyGridExportEnergySensor(coordinator=coordinator),
        SystemRunModeSensor(coordinator=coordinator),
        Ct1PowerSensor(coordinator=coordinator),
        Ct2PowerSensor(coordinator=coordinator),
    ]

    async_add_entities(entities)


class EsySensorBase(EsySunhomeEntity, SensorEntity):
    """Base class for ESY Sunhome sensors."""

    _data_attribute: str = ""

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.data is None:
            return

        value = self._get_value()
        if value is not None:
            self._attr_native_value = value
            self.async_write_ha_state()

    def _get_value(self) -> Any:
        """Get the sensor value from coordinator data."""
        if not self._data_attribute:
            # Fall back to translation key for backwards compatibility
            attr = self._attr_translation_key
        else:
            attr = self._data_attribute

        if hasattr(self.coordinator.data, attr):
            return getattr(self.coordinator.data, attr)
        return None


# =============================================================================
# Existing Sensors (Backwards Compatible)
# =============================================================================

class StateOfChargeSensor(EsySensorBase):
    """Represents the current state of charge."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_translation_key = ATTR_SOC
    _data_attribute = "battery_soc"


class EsyPowerSensor(EsySensorBase):
    """Base class for power sensors."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT


class GridPowerSensor(EsyPowerSensor):
    """Represents the current grid power."""

    _attr_translation_key = ATTR_GRID_POWER
    _attr_icon = "mdi:transmission-tower"
    _data_attribute = "grid_power"


class LoadPowerSensor(EsyPowerSensor):
    """Represents the current load power."""

    _attr_translation_key = ATTR_LOAD_POWER
    _attr_icon = "mdi:home-lightning-bolt"
    _data_attribute = "load_power"


class BatteryPowerSensor(EsyPowerSensor):
    """Represents the current battery power."""

    _attr_translation_key = ATTR_BATTERY_POWER
    _attr_icon = "mdi:home-battery-outline"
    _data_attribute = "battery_power"


class PvPowerSensor(EsyPowerSensor):
    """Represents the total PV power."""

    _attr_translation_key = ATTR_PV_POWER
    _attr_icon = "mdi:solar-power-variant"
    _data_attribute = "pv_power"


class BatteryImportSensor(EsyPowerSensor):
    """Represents the current battery import (charging) power."""

    _attr_translation_key = ATTR_BATTERY_IMPORT
    _attr_icon = "mdi:battery-arrow-up-outline"
    _data_attribute = "battery_import"


class BatteryExportSensor(EsyPowerSensor):
    """Represents the current battery export (discharging) power."""

    _attr_translation_key = ATTR_BATTERY_EXPORT
    _attr_icon = "mdi:battery-arrow-down-outline"
    _data_attribute = "battery_export"


class GridImportSensor(EsyPowerSensor):
    """Represents the current grid import power."""

    _attr_translation_key = ATTR_GRID_IMPORT
    _attr_icon = "mdi:transmission-tower-import"
    _data_attribute = "grid_import"


class GridExportSensor(EsyPowerSensor):
    """Represents the current grid export power."""

    _attr_translation_key = ATTR_GRID_EXPORT
    _attr_icon = "mdi:transmission-tower-export"
    _data_attribute = "grid_export"


class DailyPowerGenSensor(EsySensorBase):
    """Represents the daily power generation."""

    _attr_translation_key = ATTR_DAILY_POWER_GEN
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:solar-power"
    _data_attribute = "daily_energy_generation"


class RatedPowerSensor(EsySensorBase):
    """Represents the rated power."""

    _attr_entity_registry_enabled_default = False
    _attr_translation_key = ATTR_RATED_POWER
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _data_attribute = "rated_power"


class BatteryStatusTextSensor(EsySensorBase):
    """Represents the battery status text."""

    _attr_entity_registry_enabled_default = False
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_native_unit_of_measurement = None
    _attr_translation_key = ATTR_BATTERY_STATUS_TEXT
    _attr_icon = "mdi:battery-sync-outline"
    _data_attribute = "battery_status_text"


class InverterTempSensor(EsySensorBase):
    """Represents the inverter temperature."""

    _attr_translation_key = ATTR_INVERTER_TEMP
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:thermometer"
    _data_attribute = "inv_temperature"


# =============================================================================
# New v2.0.0 Sensors
# =============================================================================

class Pv1PowerSensor(EsyPowerSensor):
    """Represents PV1 power output."""

    _attr_translation_key = ATTR_PV1_POWER
    _attr_icon = "mdi:solar-panel"
    _data_attribute = "pv1_power"


class Pv2PowerSensor(EsyPowerSensor):
    """Represents PV2 power output."""

    _attr_translation_key = ATTR_PV2_POWER
    _attr_icon = "mdi:solar-panel"
    _data_attribute = "pv2_power"


class Pv1VoltageSensor(EsySensorBase):
    """Represents PV1 voltage."""

    _attr_translation_key = ATTR_PV1_VOLTAGE
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:flash"
    _data_attribute = "pv1_voltage"


class Pv1CurrentSensor(EsySensorBase):
    """Represents PV1 current."""

    _attr_translation_key = ATTR_PV1_CURRENT
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:current-dc"
    _data_attribute = "pv1_current"


class Pv2VoltageSensor(EsySensorBase):
    """Represents PV2 voltage."""

    _attr_translation_key = ATTR_PV2_VOLTAGE
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:flash"
    _data_attribute = "pv2_voltage"


class Pv2CurrentSensor(EsySensorBase):
    """Represents PV2 current."""

    _attr_translation_key = ATTR_PV2_CURRENT
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:current-dc"
    _data_attribute = "pv2_current"


class BatteryVoltageSensor(EsySensorBase):
    """Represents battery voltage."""

    _attr_translation_key = ATTR_BATTERY_VOLTAGE
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:battery-charging"
    _data_attribute = "battery_voltage"


class BatteryCurrentSensor(EsySensorBase):
    """Represents battery current."""

    _attr_translation_key = ATTR_BATTERY_CURRENT
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:current-dc"
    _data_attribute = "battery_current"


class GridVoltageSensor(EsySensorBase):
    """Represents grid voltage."""

    _attr_translation_key = ATTR_GRID_VOLTAGE
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:flash"
    _data_attribute = "grid_voltage"


class GridFrequencySensor(EsySensorBase):
    """Represents grid frequency."""

    _attr_translation_key = ATTR_GRID_FREQUENCY
    _attr_device_class = SensorDeviceClass.FREQUENCY
    _attr_native_unit_of_measurement = UnitOfFrequency.HERTZ
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:sine-wave"
    _data_attribute = "grid_frequency"


class InvOutputVoltageSensor(EsySensorBase):
    """Represents inverter output voltage."""

    _attr_translation_key = ATTR_INV_OUTPUT_VOLTAGE
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:flash"
    _data_attribute = "inv_output_voltage"


class InvOutputFrequencySensor(EsySensorBase):
    """Represents inverter output frequency."""

    _attr_translation_key = ATTR_INV_OUTPUT_FREQUENCY
    _attr_device_class = SensorDeviceClass.FREQUENCY
    _attr_native_unit_of_measurement = UnitOfFrequency.HERTZ
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:sine-wave"
    _data_attribute = "inv_output_frequency"


class TotalEnergyGenSensor(EsySensorBase):
    """Represents total energy generation."""

    _attr_translation_key = ATTR_TOTAL_ENERGY_GEN
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:solar-power"
    _data_attribute = "total_energy_generation"


class DailyPowerConsumptionSensor(EsySensorBase):
    """Represents daily power consumption."""

    _attr_translation_key = ATTR_DAILY_POWER_CONSUMPTION
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:home-lightning-bolt"
    _data_attribute = "daily_power_consumption"


class TotalPowerConsumptionSensor(EsySensorBase):
    """Represents total power consumption."""

    _attr_translation_key = ATTR_TOTAL_POWER_CONSUMPTION
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:home-lightning-bolt"
    _data_attribute = "total_power_consumption"


class DailyBattChargeSensor(EsySensorBase):
    """Represents daily battery charge energy."""

    _attr_translation_key = ATTR_DAILY_BATT_CHARGE
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:battery-charging-high"
    _data_attribute = "daily_batt_charge_energy"


class DailyBattDischargeSensor(EsySensorBase):
    """Represents daily battery discharge energy."""

    _attr_translation_key = ATTR_DAILY_BATT_DISCHARGE
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:battery-arrow-down"
    _data_attribute = "daily_batt_discharge_energy"


class DailyGridImportEnergySensor(EsySensorBase):
    """Represents daily grid import energy."""

    _attr_translation_key = ATTR_DAILY_GRID_IMPORT_ENERGY
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:transmission-tower-import"
    _data_attribute = "daily_grid_import"


class DailyGridExportEnergySensor(EsySensorBase):
    """Represents daily grid export energy."""

    _attr_translation_key = ATTR_DAILY_GRID_EXPORT_ENERGY
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:transmission-tower-export"
    _data_attribute = "daily_grid_export"


class SystemRunModeSensor(EsySensorBase):
    """Represents the system run mode."""

    _attr_translation_key = ATTR_SYSTEM_RUN_MODE
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_icon = "mdi:cog"
    _data_attribute = "system_run_mode_text"


class Ct1PowerSensor(EsyPowerSensor):
    """Represents CT1 power measurement."""

    _attr_translation_key = ATTR_CT1_POWER
    _attr_icon = "mdi:current-ac"
    _attr_entity_registry_enabled_default = False
    _data_attribute = "ct1_power"


class Ct2PowerSensor(EsyPowerSensor):
    """Represents CT2 power measurement."""

    _attr_translation_key = ATTR_CT2_POWER
    _attr_icon = "mdi:current-ac"
    _attr_entity_registry_enabled_default = False
    _data_attribute = "ct2_power"

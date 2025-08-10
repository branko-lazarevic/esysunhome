import logging

from .const import (
    ATTR_BATTERY_EXPORT,
    ATTR_BATTERY_IMPORT,
    ATTR_BATTERY_POWER,
    ATTR_BATTERY_STATUS,
    ATTR_BATTERY_STATUS_TEXT,
    ATTR_DAILY_POWER_GEN,
    ATTR_GRID_EXPORT,
    ATTR_GRID_IMPORT,
    ATTR_GRID_POWER,
    ATTR_HEATER_STATE,
    ATTR_INVERTER_TEMP,
    ATTR_LOAD_POWER,
    ATTR_PV_POWER,
    ATTR_RATED_POWER,
    ATTR_SCHEDULE_MODE,
    ATTR_SOC,
    ATTR_SYSTEM_RUN_STATUS,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import EsySunhomeEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    async_add_entities(
        [
            StateOfChargeSensor(coordinator=entry.runtime_data),
            GridPowerSensor(coordinator=entry.runtime_data),
            LoadPowerSensor(coordinator=entry.runtime_data),
            BatteryPowerSensor(coordinator=entry.runtime_data),
            PvPowerSensor(coordinator=entry.runtime_data),
            BatteryImportSensor(coordinator=entry.runtime_data),
            BatteryExportSensor(coordinator=entry.runtime_data),
            GridImportSensor(coordinator=entry.runtime_data),
            GridExportSensor(coordinator=entry.runtime_data),
            ScheduleModeSensor(coordinator=entry.runtime_data),
            DailyPowerGenSensor(coordinator=entry.runtime_data),
            RatedPowerSensor(coordinator=entry.runtime_data),
            BatteryStatusTextSensor(coordinator=entry.runtime_data),
            InverterTempSensor(coordinator=entry.runtime_data),
        ]
    )


class EsySensorBase(EsySunhomeEntity, SensorEntity):
    """Base class for EsySunhome sensors."""

    @callback
    def _handle_coordinator_update(self) -> None:
        if hasattr(self.coordinator.data, self._attr_translation_key):
            self._attr_native_value = getattr(
                self.coordinator.data, self._attr_translation_key
            )
            self.async_write_ha_state()


class StateOfChargeSensor(EsySensorBase):
    """Represents the current state of charge."""

    _attr_native_unit_of_measurement = "%"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_translation_key = ATTR_SOC


class EsyPowerSensor(EsySensorBase):
    """Base class of power sensors."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT


class GridPowerSensor(EsyPowerSensor):
    """Represents the current grid power."""

    _attr_translation_key = ATTR_GRID_POWER
    _attr_icon = "mdi:transmission-tower"


class LoadPowerSensor(EsyPowerSensor):
    """Represents the current load power."""

    _attr_translation_key = ATTR_LOAD_POWER
    _attr_icon = "mdi:home-lightning-bolt"


class BatteryPowerSensor(EsyPowerSensor):
    """Represents the current battery power."""

    _attr_translation_key = ATTR_BATTERY_POWER
    _attr_icon = "mdi:home-battery-outline"


class PvPowerSensor(EsyPowerSensor):
    """Represents the current PV power."""

    _attr_translation_key = ATTR_PV_POWER
    _attr_icon = "mdi:solar-power-variant"


class BatteryImportSensor(EsyPowerSensor):
    """Represents the current battery import power."""

    _attr_translation_key = ATTR_BATTERY_IMPORT
    _attr_icon = "mdi:battery-arrow-up-outline"


class BatteryExportSensor(EsyPowerSensor):
    """Represents the current battery export power."""

    _attr_translation_key = ATTR_BATTERY_EXPORT
    _attr_icon = "mdi:battery-arrow-down-outline"


class GridImportSensor(EsyPowerSensor):
    """Represents the current grid import power."""

    _attr_translation_key = ATTR_GRID_IMPORT
    _attr_icon = "mdi:transmission-tower-import"


class GridExportSensor(EsyPowerSensor):
    """Represents the current grid export power."""

    _attr_translation_key = ATTR_GRID_EXPORT
    _attr_icon = "mdi:transmission-tower-export"


class ScheduleModeSensor(EsySensorBase):
    """Represents the current schedule mode."""

    _attr_entity_registry_enabled_default = False
    _attr_translation_key = ATTR_SCHEDULE_MODE


class BatteryStatusSensor(EsySensorBase):
    """Represents the current battery status."""

    _attr_entity_registry_enabled_default = False
    _attr_translation_key = ATTR_BATTERY_STATUS


class SystemRunStatusSensor(EsySensorBase):
    """Represents the current system run status."""

    _attr_entity_registry_enabled_default = False
    _attr_translation_key = ATTR_SYSTEM_RUN_STATUS


class DailyPowerGenSensor(EsySensorBase):
    """Represents the current daily power generation."""

    _attr_translation_key = ATTR_DAILY_POWER_GEN
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_state_class = SensorStateClass.MEASUREMENT


class RatedPowerSensor(EsySensorBase):
    """Represents the current rated power."""

    _attr_entity_registry_enabled_default = False
    _attr_translation_key = ATTR_RATED_POWER
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_state_class = SensorStateClass.MEASUREMENT


class BatteryStatusTextSensor(EsySensorBase):
    """Represents the current battery status text."""

    _attr_entity_registry_enabled_default = False
    _attr_translation_key = ATTR_BATTERY_STATUS_TEXT


class InverterTempSensor(EsySensorBase):
    """Represents the current inverter temperature."""

    _attr_translation_key = ATTR_INVERTER_TEMP
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT


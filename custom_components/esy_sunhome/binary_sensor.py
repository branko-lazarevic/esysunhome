"""ESY Sunhome binary sensor platform."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_GRID_ACTIVE,
    ATTR_HEATER_STATE,
    ATTR_LOAD_ACTIVE,
    ATTR_PV_ACTIVE,
    ATTR_BATTERY_ACTIVE,
    ATTR_ON_OFF_GRID_MODE,
)
from .entity import EsySunhomeEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary_sensor platform."""
    coordinator = entry.runtime_data

    async_add_entities(
        [
            GridActiveSensor(coordinator=coordinator),
            LoadActiveSensor(coordinator=coordinator),
            PvActiveSensor(coordinator=coordinator),
            BatteryActiveSensor(coordinator=coordinator),
            HeaterStateSensor(coordinator=coordinator),
            OnGridModeSensor(coordinator=coordinator),
        ]
    )


class EsyBinarySensorBase(EsySunhomeEntity, BinarySensorEntity):
    """Base class for ESY Sunhome binary sensors."""

    _attr_device_class = BinarySensorDeviceClass.POWER
    _attr_is_on = False
    _data_attribute: str = ""

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.data is None:
            return

        value = self._get_value()
        if value is not None:
            self._attr_is_on = self._compute_is_on(value)
            self.async_write_ha_state()

    def _get_value(self) -> Any:
        """Get the sensor value from coordinator data."""
        if self._data_attribute and hasattr(self.coordinator.data, self._data_attribute):
            return getattr(self.coordinator.data, self._data_attribute)
        if hasattr(self.coordinator.data, self._attr_translation_key):
            return getattr(self.coordinator.data, self._attr_translation_key)
        return None

    def _compute_is_on(self, value: Any) -> bool:
        """Compute the is_on value from the raw value."""
        if isinstance(value, bool):
            return value
        # For backwards compatibility with old format
        return value == 1 or value > 0


class GridActiveSensor(EsyBinarySensorBase):
    """Represents whether the grid is active."""

    _attr_translation_key = ATTR_GRID_ACTIVE
    _attr_icon = "mdi:transmission-tower"
    _data_attribute = "grid_active"


class LoadActiveSensor(EsyBinarySensorBase):
    """Represents whether the load is active."""

    _attr_translation_key = ATTR_LOAD_ACTIVE
    _attr_icon = "mdi:home-lightning-bolt"
    _data_attribute = "load_active"


class PvActiveSensor(EsyBinarySensorBase):
    """Represents whether PV is generating power."""

    _attr_translation_key = ATTR_PV_ACTIVE
    _attr_icon = "mdi:solar-panel"
    _data_attribute = "pv_active"


class BatteryActiveSensor(EsyBinarySensorBase):
    """Represents whether the battery is active."""

    _attr_translation_key = ATTR_BATTERY_ACTIVE
    _attr_icon = "mdi:home-battery-outline"
    _data_attribute = "battery_active"


class HeaterStateSensor(EsyBinarySensorBase):
    """Represents the heater state."""

    _attr_entity_registry_enabled_default = False
    _attr_translation_key = ATTR_HEATER_STATE
    _attr_icon = "mdi:radiator"
    _data_attribute = "heating_state"


class OnGridModeSensor(EsyBinarySensorBase):
    """Represents whether the system is on-grid."""

    _attr_translation_key = ATTR_ON_OFF_GRID_MODE
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_icon = "mdi:transmission-tower"
    _data_attribute = "on_off_grid_mode"

    def _compute_is_on(self, value: Any) -> bool:
        """On-grid mode: 1 = on-grid (True), 0 = off-grid (False)."""
        return value == 1

import logging

from .const import (
    ATTR_GRID_ACTIVE,
    ATTR_HEATER_STATE,
    ATTR_LOAD_ACTIVE,
    ATTR_PV_ACTIVE,
    ATTR_BATTERY_ACTIVE,
)
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import EsySunhomeEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary_sensor platform."""

    async_add_entities(
        [
            GridActiveSensor(coordinator=entry.runtime_data),
            LoadActiveSensor(coordinator=entry.runtime_data),
            PvActiveSensor(coordinator=entry.runtime_data),
            BatteryActiveSensor(coordinator=entry.runtime_data),
            HeaterStateSensor(coordinator=entry.runtime_data),
        ]
    )


class EsyBinarySensorBase(EsySunhomeEntity, BinarySensorEntity):
    """Base class for EsySunhome binary sensors."""

    _attr_device_class = BinarySensorDeviceClass.POWER
    _attr_is_on = False

    @callback
    def _handle_coordinator_update(self) -> None:
        if hasattr(self.coordinator.data, self._attr_translation_key):
            # Values: 0=inactive, 1=flow direction A, 2=flow direction B
            # Consider active if value is non-zero
            value = getattr(self.coordinator.data, self._attr_translation_key)
            self._attr_is_on = value is not None and value != 0
            self.async_write_ha_state()


class GridActiveSensor(EsyBinarySensorBase):
    """Represents the current grid active power."""

    _attr_translation_key = ATTR_GRID_ACTIVE
    _attr_icon = "mdi:transmission-tower"


class LoadActiveSensor(EsyBinarySensorBase):
    """Represents the current load active power."""

    _attr_translation_key = ATTR_LOAD_ACTIVE
    _attr_icon = "mdi:home-lightning-bolt"


class PvActiveSensor(EsyBinarySensorBase):
    """Represents the current PV active power."""

    _attr_translation_key = ATTR_PV_ACTIVE
    _attr_icon = "mdi:solar-panel"


class BatteryActiveSensor(EsyBinarySensorBase):
    """Represents the current battery active power."""

    _attr_translation_key = ATTR_BATTERY_ACTIVE
    _attr_icon = "mdi:home-battery-outline"


class HeaterStateSensor(EsyBinarySensorBase):
    """Represents the current heater state."""

    _attr_entity_registry_enabled_default = False
    _attr_translation_key = ATTR_HEATER_STATE
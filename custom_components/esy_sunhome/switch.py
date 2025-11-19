"""Switch platform for ESY Sunhome."""
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENABLE_POLLING, DEFAULT_ENABLE_POLLING
from .entity import EsySunhomeEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ESY Sunhome switch based on a config entry."""
    coordinator = entry.runtime_data

    async_add_entities([
        ESYSunhomePollingSwitch(coordinator=coordinator, entry=entry),
    ])


class ESYSunhomePollingSwitch(EsySunhomeEntity, SwitchEntity):
    """Switch to control API polling."""

    _attr_translation_key = "api_polling"
    _attr_name = "API Polling"
    _attr_icon = "mdi:reload"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_api_polling"
        self._attr_entity_registry_enabled_default = True

    @property
    def is_on(self) -> bool:
        """Return true if polling is enabled."""
        return self._entry.options.get(CONF_ENABLE_POLLING, DEFAULT_ENABLE_POLLING)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on polling."""
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_ENABLE_POLLING: True},
        )
        self.coordinator.set_polling_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off polling."""
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_ENABLE_POLLING: False},
        )
        self.coordinator.set_polling_enabled(False)
        self.async_write_ha_state()

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .battery import BatteryState
from .entity import EsySunhomeEntity
from .const import ATTR_SCHEDULE_MODE

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        [
            ModeSelect(coordinator=entry.runtime_data),
        ]
    )


class ModeSelect(EsySunhomeEntity, SelectEntity):
    """Represents the operating mode of the heat pump."""

    _attr_translation_key = ATTR_SCHEDULE_MODE
    _attr_options = list(BatteryState.modes.values())
    _attr_current_option = _attr_options[0]

    @callback
    def _handle_coordinator_update(self) -> None:
        if hasattr(self.coordinator.data, "mode"):
            self._attr_current_option = self.coordinator.data.mode
            self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Set operating mode."""
        await self.coordinator.api.set_value(ATTR_SCHEDULE_MODE, self.get_mode_key(option))

    def get_mode_key(value: str) -> int:
        for key, mode in BatteryState.modes.items():
            if mode == value:
                return key
        return None  # Return None if the value is not found
import logging
from homeassistant.components.sensor import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from .coordinator import EsySunhomeCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ESY Sunhome from a config entry."""

    coordinator = EsySunhomeCoordinator(hass=hass)
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    if entry.runtime_data:
        await entry.runtime_data.shutdown()

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


from homeassistant.components.sensor import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from .coordinator import EsySunhomeCoordinator
from .const import CONF_ENABLE_POLLING, DEFAULT_ENABLE_POLLING

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ESY Sunhome from a config entry."""

    coordinator = EsySunhomeCoordinator(hass=hass)
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Register options update listener
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    
    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update options."""
    coordinator = entry.runtime_data
    
    # Update polling state
    polling_enabled = entry.options.get(CONF_ENABLE_POLLING, DEFAULT_ENABLE_POLLING)
    coordinator.set_polling_enabled(polling_enabled)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    if entry.runtime_data:
        await entry.runtime_data.shutdown()

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

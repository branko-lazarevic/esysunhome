import logging

from homeassistant.components.sensor import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from .coordinator import EsySunhomeCoordinator
from .const import (
    CONF_ENABLE_POLLING,
    CONF_USER_ID,
    CONF_USERNAME,
    CONF_PASSWORD,
    DEFAULT_ENABLE_POLLING,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old entry to new version."""
    _LOGGER.debug("Migrating config entry from version %s", entry.version)

    if entry.version == 1:
        # Migrate v1 to v2: fetch user_id from API
        _LOGGER.info("Migrating config entry v1 to v2: fetching user_id")

        new_data = {**entry.data}

        # Only fetch user_id if not already present
        if CONF_USER_ID not in new_data or not new_data.get(CONF_USER_ID):
            try:
                from .config_flow import fetch_devices

                username = new_data.get(CONF_USERNAME)
                password = new_data.get(CONF_PASSWORD)

                if username and password:
                    devices, user_id = await fetch_devices(username, password)
                    if user_id:
                        new_data[CONF_USER_ID] = user_id
                        _LOGGER.info("Migration: extracted user_id %s", user_id)
                    else:
                        _LOGGER.warning("Migration: could not extract user_id from device data")
                else:
                    _LOGGER.warning("Migration: missing username or password")
            except Exception as err:
                _LOGGER.error("Migration: failed to fetch user_id: %s", err)
                # Don't block migration - user_id is optional for basic functionality

        hass.config_entries.async_update_entry(entry, data=new_data, version=2)
        _LOGGER.info("Migration to v2 complete")

    return True


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

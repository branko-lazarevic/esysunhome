import logging

from homeassistant.components.sensor import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from .coordinator import EsySunhomeCoordinator
from .const import (
    CONF_ENABLE_POLLING,
    CONF_USER_ID,
    CONF_DEVICE_SN,
    CONF_DEVICE_ID,
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

    if entry.version < 3:
        # Migrate to v3: fetch user_id and device_sn from API
        _LOGGER.info("Migrating config entry to v3: fetching user_id and device_sn")

        new_data = {**entry.data}

        # Fetch user_id and device_sn if not already present
        needs_user_id = CONF_USER_ID not in new_data or not new_data.get(CONF_USER_ID)
        needs_device_sn = CONF_DEVICE_SN not in new_data or not new_data.get(CONF_DEVICE_SN)
        
        if needs_user_id or needs_device_sn:
            try:
                from .config_flow import fetch_devices

                username = new_data.get(CONF_USERNAME)
                password = new_data.get(CONF_PASSWORD)
                device_id = new_data.get(CONF_DEVICE_ID)

                if username and password:
                    devices, user_id, device_sn_map = await fetch_devices(username, password)
                    
                    if needs_user_id and user_id:
                        new_data[CONF_USER_ID] = user_id
                        _LOGGER.info("Migration: extracted user_id %s", user_id)
                    
                    if needs_device_sn and device_id and device_sn_map:
                        device_sn = device_sn_map.get(str(device_id))
                        if device_sn:
                            new_data[CONF_DEVICE_SN] = device_sn
                            _LOGGER.info("Migration: extracted device_sn %s for device %s", device_sn, device_id)
                        else:
                            _LOGGER.warning("Migration: could not find device_sn for device %s", device_id)
                else:
                    _LOGGER.warning("Migration: missing username or password")
            except Exception as err:
                _LOGGER.error("Migration: failed to fetch device data: %s", err)
                # Don't block migration - can still work with device_id as fallback

        hass.config_entries.async_update_entry(entry, data=new_data, version=3)
        _LOGGER.info("Migration to v3 complete")

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

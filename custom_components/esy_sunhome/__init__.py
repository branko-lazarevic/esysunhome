"""ESY Sunhome Integration - Dynamic Protocol Version."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_DEVICE_ID,
    CONF_DEVICE_SN,
    CONF_PV_POWER,
    CONF_TP_TYPE,
    CONF_MCU_VERSION,
    DEFAULT_PV_POWER,
    DEFAULT_TP_TYPE,
    DEFAULT_MCU_VERSION,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the ESY Sunhome component.
    
    This is called for YAML configuration (which we don't support).
    We only support config entry setup via the UI.
    """
    return True


def _import_aiomqtt():
    """Import aiomqtt in executor thread to avoid blocking warnings."""
    import aiomqtt  # noqa: F401
    return True


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry to new version.
    
    This handles migration from older config entry versions to the current version.
    """
    try:
        current_version = config_entry.version
        _LOGGER.info("Checking migration for config entry version %s (target: 2)", current_version)

        # Handle missing or 0 version (very old entries)
        if current_version is None or current_version == 0:
            current_version = 1
            _LOGGER.info("Config entry has no version, treating as version 1")

        if current_version > 2:
            # Future version - can't downgrade, but try to continue anyway
            _LOGGER.warning("Config entry has future version %s, attempting to use anyway", current_version)
            return True

        if current_version < 2:
            # Migration to v2: add protocol parameters
            _LOGGER.info("Migrating config entry from version %s to version 2", current_version)
            new_data = {**config_entry.data}
            
            # Add default protocol parameters if missing
            if CONF_PV_POWER not in new_data:
                new_data[CONF_PV_POWER] = DEFAULT_PV_POWER
            if CONF_TP_TYPE not in new_data:
                new_data[CONF_TP_TYPE] = DEFAULT_TP_TYPE
            if CONF_MCU_VERSION not in new_data:
                new_data[CONF_MCU_VERSION] = DEFAULT_MCU_VERSION
            
            hass.config_entries.async_update_entry(config_entry, data=new_data, version=2)
            _LOGGER.info("Migration to version 2 successful")
        else:
            _LOGGER.info("Config entry already at version %s, no migration needed", current_version)

        return True
        
    except Exception as e:
        _LOGGER.error("Migration failed with error: %s", e)
        # Return True anyway to allow loading - better to try than fail
        return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ESY Sunhome from a config entry."""
    _LOGGER.info("Setting up ESY Sunhome integration")
    
    # Pre-import aiomqtt in executor to avoid blocking call warnings
    await hass.async_add_executor_job(_import_aiomqtt)
    
    # Now import our modules (coordinator imports aiomqtt, but it's already cached)
    from .esysunhome import ESYSunhomeAPI
    from .protocol_api import get_protocol_api
    from .coordinator import ESYSunhomeCoordinator
    
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    device_id = entry.data.get(CONF_DEVICE_ID, "")
    device_sn = entry.data.get(CONF_DEVICE_SN, device_id)
    
    # Get protocol parameters (with defaults for backward compatibility)
    pv_power = entry.data.get(CONF_PV_POWER, DEFAULT_PV_POWER)
    tp_type = entry.data.get(CONF_TP_TYPE, DEFAULT_TP_TYPE)
    mcu_version = entry.data.get(CONF_MCU_VERSION, DEFAULT_MCU_VERSION)
    
    # Create API instance
    api = ESYSunhomeAPI(username, password, device_id)
    
    protocol = None
    try:
        # Authenticate
        await api.get_bearer_token()
        _LOGGER.info("Successfully authenticated with ESY API")
        
        # Load protocol definition from API
        protocol_api = get_protocol_api(api.access_token)
        protocol = await protocol_api.get_protocol_definition(
            pv_power=pv_power,
            tp_type=tp_type,
            mcu_version=mcu_version,
        )
        
        if protocol:
            _LOGGER.info("Loaded protocol: %d input regs, %d holding regs, %d segments",
                        len(protocol.input_registers),
                        len(protocol.holding_registers),
                        len(protocol.segments))
        else:
            _LOGGER.warning("Failed to load protocol, using fallback")
        
    except Exception as e:
        _LOGGER.error("Failed to set up ESY Sunhome: %s", e)
        raise
    
    # Create coordinator with protocol
    coordinator = ESYSunhomeCoordinator(
        hass=hass,
        api=api,
        device_sn=device_sn,
        config_entry=entry,
        protocol=protocol,
    )
    
    # Start coordinator
    await coordinator.async_config_entry_first_refresh()
    
    # Store coordinator
    entry.runtime_data = coordinator
    
    # Register debug dump service
    async def async_dump_debug(call):
        """Service to dump debug info to logs."""
        _LOGGER.info("=" * 60)
        _LOGGER.info("ESY SUNHOME DEBUG DUMP")
        _LOGGER.info("=" * 60)
        
        # Config info
        _LOGGER.info("Config: device_sn=%s, pv_power=%s, tp_type=%s, mcu_version=%s",
                    device_sn, pv_power, tp_type, mcu_version)
        
        # MQTT status
        _LOGGER.info("MQTT: connected=%s, last_message=%s",
                    coordinator._mqtt_connected,
                    coordinator._last_mqtt_time)
        _LOGGER.info("Topics: UP=%s, DOWN=%s",
                    coordinator._topic_up, 
                    getattr(coordinator, '_topic_down', 'N/A'))
        
        # Protocol info
        if coordinator.protocol:
            _LOGGER.info("Protocol: %d registers defined",
                        len(getattr(coordinator.protocol, '_registers', [])))
        
        # Raw values
        raw = getattr(coordinator, '_last_raw_values', {})
        _LOGGER.info("Raw values (%d keys):", len(raw))
        for key, value in sorted(raw.items()):
            _LOGGER.info("  %s = %s", key, value)
        
        # Parsed data
        if coordinator.data and hasattr(coordinator.data, 'data'):
            parsed = coordinator.data.data
            _LOGGER.info("Parsed values (%d keys):", len(parsed))
            for key, value in sorted(parsed.items()):
                if not key.startswith('_'):  # Skip internal keys
                    _LOGGER.info("  %s = %s", key, value)
        
        _LOGGER.info("=" * 60)
        _LOGGER.info("END DEBUG DUMP")
        _LOGGER.info("=" * 60)
    
    hass.services.async_register(DOMAIN, "dump_debug", async_dump_debug)
    
    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    _LOGGER.info("ESY Sunhome integration setup complete")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading ESY Sunhome integration")
    
    # Unregister services
    hass.services.async_remove(DOMAIN, "dump_debug")
    
    # Stop coordinator
    coordinator = entry.runtime_data
    if coordinator:
        await coordinator.async_shutdown()
    
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)

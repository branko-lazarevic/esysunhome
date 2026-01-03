"""Diagnostics support for ESY Sunhome integration.

Users can download diagnostics via:
Settings → Devices & Services → ESY Sunhome → 3-dot menu → Download Diagnostics

This provides debug info including:
- Raw MQTT register values
- Parsed/computed sensor values
- Configuration (with sensitive data redacted)
- Connection status
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import EsySunhomeCoordinator

_LOGGER = logging.getLogger(__name__)

# Keys to redact from diagnostics for privacy
TO_REDACT = {
    "password",
    "token",
    "access_token",
    "refresh_token",
    "username",
    "email",
    "user_id",
    "userId",
    "client_id",
    "clientId",
    "serial_number",
    "serialNumber",
    "manufactureSn",
    "productSn",
}

# Keys to partially redact (show first/last few chars)
TO_PARTIAL_REDACT = {
    "device_id",
    "deviceId", 
    "sn",
}


def _partial_redact(value: str, show_chars: int = 4) -> str:
    """Partially redact a string, showing first and last few characters."""
    if not isinstance(value, str) or len(value) <= show_chars * 2:
        return "**REDACTED**"
    return f"{value[:show_chars]}...{value[-show_chars:]}"


def _redact_dict(data: dict, to_redact: set, to_partial: set) -> dict:
    """Recursively redact sensitive data from a dictionary."""
    result = {}
    for key, value in data.items():
        key_lower = key.lower()
        
        if any(r.lower() in key_lower for r in to_redact):
            result[key] = "**REDACTED**"
        elif any(r.lower() in key_lower for r in to_partial):
            result[key] = _partial_redact(str(value)) if value else None
        elif isinstance(value, dict):
            result[key] = _redact_dict(value, to_redact, to_partial)
        elif isinstance(value, list):
            result[key] = [
                _redact_dict(item, to_redact, to_partial) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value
    
    return result


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: EsySunhomeCoordinator = entry.runtime_data
    
    # Get raw and parsed data
    raw_values = {}
    parsed_values = {}
    mqtt_status = {}
    
    if coordinator.data:
        # The coordinator.data is the parsed BatteryState
        if hasattr(coordinator.data, 'data'):
            parsed_values = dict(coordinator.data.data)
    
    # Get raw MQTT values if available
    if hasattr(coordinator, '_last_raw_values'):
        raw_values = dict(coordinator._last_raw_values)
    
    # Get MQTT connection status
    mqtt_status = {
        "connected": getattr(coordinator, '_mqtt_connected', False),
        "last_message_time": getattr(coordinator, '_last_mqtt_time', None),
        "topic_up": getattr(coordinator, '_topic_up', None),
        "topic_down": getattr(coordinator, '_topic_down', None),
        "topic_event": getattr(coordinator, '_topic_event', None),
        "topic_alarm": getattr(coordinator, '_topic_alarm', None),
    }
    
    # Get protocol info
    protocol_info = {}
    if hasattr(coordinator, 'protocol') and coordinator.protocol:
        protocol = coordinator.protocol
        protocol_info = {
            "pv_power": getattr(protocol, 'pv_power', None),
            "tp_type": getattr(protocol, 'tp_type', None),
            "mcu_version": getattr(protocol, 'mcu_version', None),
            "num_registers": len(getattr(protocol, '_registers', [])),
        }
    
    # Build diagnostics
    diagnostics = {
        "integration_version": "2.1.8",
        "config_entry": {
            "entry_id": entry.entry_id,
            "version": entry.version,
            "domain": entry.domain,
            "title": entry.title,
            "data": _redact_dict(dict(entry.data), TO_REDACT, TO_PARTIAL_REDACT),
            "options": dict(entry.options),
        },
        "mqtt_status": mqtt_status,
        "protocol_info": protocol_info,
        "raw_mqtt_values": _redact_dict(raw_values, TO_REDACT, TO_PARTIAL_REDACT),
        "parsed_values": _redact_dict(parsed_values, TO_REDACT, TO_PARTIAL_REDACT),
        "coordinator_info": {
            "last_update_success": coordinator.last_update_success,
            "last_exception": str(coordinator.last_exception) if coordinator.last_exception else None,
            "update_interval": str(coordinator.update_interval),
        },
    }
    
    # Add register dump if available
    if hasattr(coordinator, 'protocol') and coordinator.protocol:
        try:
            registers = []
            for reg in getattr(coordinator.protocol, '_registers', []):
                registers.append({
                    "name": reg.data_key,
                    "address": reg.address,
                    "function_code": reg.function_code,
                    "coefficient": reg.coefficient,
                    "signed": reg.signed,
                })
            diagnostics["register_definitions"] = registers
        except Exception as e:
            diagnostics["register_definitions_error"] = str(e)
    
    return diagnostics

"""ESY Sunhome power-control number entities.

Exposes the inverter's settable power/limit registers as Home Assistant number
controls. The register *addresses* are resolved per-model from the dynamic
register map (so this works across single- and three-phase models), and values
are written over the same MQTT register-write path used for mode changes.

Note on units: this firmware exposes battery charge/discharge as *current* (A)
and export limit as a *percentage* of rated power — these are the native
settable registers (the mobile app's watt values are converted to these by the
backend). Entities are only created for registers present on the device.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import EsySunhomeEntity
from .protocol_api import FC_READ_HOLDING

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PowerControlDescriptor:
    """Describes a settable power-control register exposed as a number."""

    data_key: str          # register dataKey to resolve + write
    translation_key: str   # unique-id suffix
    name: str
    unit: str
    min_value: float
    max_value: float
    step: float
    icon: str


# Candidate controls. Only those whose register exists on the device's model
# (per the fetched register map) are actually created.
CONTROLS: list[PowerControlDescriptor] = [
    PowerControlDescriptor(
        "batteryChargingCurrent", "battery_charge_current",
        "Battery Charge Current", "A", 0, 100, 0.1, "mdi:battery-arrow-up",
    ),
    PowerControlDescriptor(
        "batteryDischargeCurrent", "battery_discharge_current",
        "Battery Discharge Current", "A", 0, 100, 0.1, "mdi:battery-arrow-down",
    ),
    PowerControlDescriptor(
        "antiBackflowPowerPercentage", "export_limit_percent",
        "Export Power Limit", "%", 0, 100, 1, "mdi:transmission-tower-export",
    ),
    PowerControlDescriptor(
        "maxOutputPowerPercent", "max_output_power_percent",
        "Max Output Power", "%", 0, 100, 1, "mdi:flash",
    ),
    PowerControlDescriptor(
        "onGridSocLimit", "on_grid_soc_limit",
        "On-Grid SOC Limit", "%", 0, 100, 1, "mdi:battery-charging-50",
    ),
    PowerControlDescriptor(
        "offGridSocLimit", "off_grid_soc_limit",
        "Off-Grid SOC Limit", "%", 0, 100, 1, "mdi:battery-charging-10",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up power-control numbers for registers present on this model."""
    coordinator = entry.runtime_data
    protocol = coordinator.protocol

    entities: list[ESYPowerControlNumber] = []
    for desc in CONTROLS:
        reg = (
            protocol.get_register_by_key(desc.data_key, FC_READ_HOLDING)
            if protocol else None
        )
        if reg is None:
            _LOGGER.debug(
                "Skipping number %s: register not in this model's map", desc.data_key
            )
            continue
        if not getattr(reg, "can_set", False):
            _LOGGER.debug("Skipping number %s: register not settable", desc.data_key)
            continue
        entities.append(ESYPowerControlNumber(coordinator, desc, reg))

    if entities:
        async_add_entities(entities)
        _LOGGER.info("Added %d power-control number entities", len(entities))


class ESYPowerControlNumber(EsySunhomeEntity, NumberEntity):
    """A settable power-control register exposed as a number entity."""

    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, desc: PowerControlDescriptor, reg) -> None:
        # translation_key must be set before super().__init__ (used for unique_id)
        self._attr_translation_key = desc.translation_key
        super().__init__(coordinator)
        self._desc = desc
        self._reg = reg
        self._attr_name = desc.name
        self._attr_native_unit_of_measurement = desc.unit
        self._attr_native_min_value = desc.min_value
        self._attr_native_max_value = desc.max_value
        self._attr_native_step = desc.step
        self._attr_icon = desc.icon
        self._optimistic: Optional[float] = None

    @property
    def native_value(self) -> Optional[float]:
        """Current setting — from telemetry if present, else last value we wrote."""
        try:
            val = self.coordinator.data.get(self._desc.data_key)
        except Exception:  # noqa: BLE001 - coordinator data may be missing early
            val = None
        return val if val is not None else self._optimistic

    async def async_set_native_value(self, value: float) -> None:
        """Write the value to the register (scaled by its coefficient)."""
        coef = self._reg.coefficient or 1
        raw = int(round(value / coef))
        ok = await self.coordinator.write_register(self._reg.address, raw)
        if not ok:
            raise HomeAssistantError(
                f"Failed to set {self._desc.name} (MQTT not connected?)"
            )
        self._optimistic = value
        self.async_write_ha_state()
        _LOGGER.info(
            "Set %s = %s%s (register %d = %d)",
            self._desc.name, value, self._desc.unit, self._reg.address, raw,
        )

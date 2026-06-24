"""ESY Sunhome number entities.

Two groups:
  * Power-control registers (charge/discharge current, export %, SOC limits) —
    settable inverter registers, written over the MQTT register-write path,
    with addresses resolved per-model from the dynamic register map.
  * BEM SOC cutoffs (purchase/sale/use) — part of the server-side BEM schedule,
    written via the schedule REST API.

Power-control entities are only created for registers present on the device's
model. Units: this firmware exposes battery charge/discharge as *current* (A)
and export limit as a *percentage* of rated power (the mobile app's watt values
are converted to these by the backend).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import EsySunhomeEntity
from .protocol_api import FC_READ_HOLDING

if TYPE_CHECKING:
    from .coordinator import ESYSunhomeCoordinator

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Power-control registers (MQTT register writes)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# BEM SOC cutoffs (schedule REST API) — from the phmarc fork
# (translation_key, name, schedule field, icon)
# ---------------------------------------------------------------------------
SOC_CUTOFFS = [
    ("soc_purchase_cutoff", "SOC Purchase Cutoff", "chargeCutOff", "mdi:battery-charging-60"),
    ("soc_sale_cutoff", "SOC Sale Cutoff", "dischargeCutOff", "mdi:battery-minus-outline"),
    ("soc_use_cutoff", "SOC Use Cutoff", "releaseCutOff", "mdi:battery-outline"),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up power-control and BEM SOC-cutoff number entities."""
    coordinator = entry.runtime_data
    protocol = coordinator.protocol

    entities: list[NumberEntity] = []

    # Power-control registers — only those present + settable on this model.
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

    # BEM SOC cutoffs (schedule API).
    entities.extend(
        ESYSunhomeSOCNumber(coordinator, key, name, field, icon)
        for key, name, field, icon in SOC_CUTOFFS
    )

    if entities:
        async_add_entities(entities)
        _LOGGER.info("Added %d number entities", len(entities))


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


class ESYSunhomeSOCNumber(EsySunhomeEntity, NumberEntity):
    """Number entity for a BEM SOC cutoff value (server-side schedule)."""

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        coordinator: "ESYSunhomeCoordinator",
        translation_key: str,
        name: str,
        field: str,
        icon: str,
    ) -> None:
        self._attr_translation_key = translation_key
        self._attr_name = name
        self._field = field
        self._attr_icon = icon
        super().__init__(coordinator)

    @property
    def native_value(self) -> float | None:
        schedule = self.coordinator.schedule_data
        if schedule is None:
            return None
        val = schedule.get(self._field)
        if val is None:
            return None
        return float(val)

    async def async_set_native_value(self, value: float) -> None:
        """Set the SOC cutoff via the schedule API."""
        coordinator = self.coordinator
        # Fetch the latest schedule so we send back the full payload
        schedule = await coordinator.api.get_schedule()
        schedule[self._field] = int(value)
        await coordinator.api.save_schedule(schedule)
        coordinator.schedule_data = schedule
        self.async_write_ha_state()

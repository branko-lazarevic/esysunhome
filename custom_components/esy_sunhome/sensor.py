"""ESY Sunhome sensor platform with comprehensive sensors."""

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import EsySunhomeEntity
from .const import (
    ATTR_SOC,
    ATTR_GRID_POWER,
    ATTR_LOAD_POWER,
    ATTR_BATTERY_POWER,
    ATTR_PV_POWER,
    ATTR_PV1_POWER,
    ATTR_PV2_POWER,
    ATTR_BATTERY_IMPORT,
    ATTR_BATTERY_EXPORT,
    ATTR_GRID_IMPORT,
    ATTR_GRID_EXPORT,
    ATTR_DAILY_POWER_GEN,
    ATTR_DAILY_CONSUMPTION,
    ATTR_DAILY_GRID_EXPORT,
    ATTR_DAILY_BATT_CHARGE,
    ATTR_DAILY_BATT_DISCHARGE,
    ATTR_TOTAL_POWER_GEN,
    ATTR_GRID_VOLTAGE,
    ATTR_GRID_FREQUENCY,
    ATTR_PV1_VOLTAGE,
    ATTR_PV1_CURRENT,
    ATTR_PV2_VOLTAGE,
    ATTR_PV2_CURRENT,
    ATTR_BATTERY_VOLTAGE,
    ATTR_BATTERY_CURRENT,
    ATTR_INVERTER_TEMP,
    ATTR_DCDC_TEMP,
    ATTR_BATTERY_SOH,
    ATTR_RATED_POWER,
    ATTR_BATTERY_STATUS_TEXT,
    ATTR_CT1_POWER,
    ATTR_CT2_POWER,
    ATTR_METER_POWER,
    ATTR_ENERGY_FLOW_PV,
    ATTR_ENERGY_FLOW_BATT,
    ATTR_ENERGY_FLOW_GRID,
    ATTR_ENERGY_FLOW_LOAD,
    ATTR_SYSTEM_RUN_MODE,
    ATTR_SYSTEM_RUN_STATUS,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    entities = [
        # === CORE POWER SENSORS ===
        StateOfChargeSensor(coordinator=entry.runtime_data),
        PvPowerSensor(coordinator=entry.runtime_data),
        Pv1PowerSensor(coordinator=entry.runtime_data),
        Pv2PowerSensor(coordinator=entry.runtime_data),
        DcPvPowerSensor(coordinator=entry.runtime_data),
        AcPvPowerSensor(coordinator=entry.runtime_data),
        GridPowerSensor(coordinator=entry.runtime_data),
        LoadPowerSensor(coordinator=entry.runtime_data),
        BatteryPowerSensor(coordinator=entry.runtime_data),
        
        # === DIRECTIONAL POWER ===
        BatteryImportSensor(coordinator=entry.runtime_data),
        BatteryExportSensor(coordinator=entry.runtime_data),
        GridImportSensor(coordinator=entry.runtime_data),
        GridExportSensor(coordinator=entry.runtime_data),
        
        # === DAILY ENERGY ===
        DailyPowerGenSensor(coordinator=entry.runtime_data),
        DailyConsumptionSensor(coordinator=entry.runtime_data),
        DailyGridExportSensor(coordinator=entry.runtime_data),
        DailyBattChargeSensor(coordinator=entry.runtime_data),
        DailyBattDischargeSensor(coordinator=entry.runtime_data),
        
        # === TOTAL ENERGY ===
        TotalPowerGenSensor(coordinator=entry.runtime_data),
        
        # === VOLTAGE & CURRENT ===
        GridVoltageSensor(coordinator=entry.runtime_data),
        GridFrequencySensor(coordinator=entry.runtime_data),
        Pv1VoltageSensor(coordinator=entry.runtime_data),
        Pv1CurrentSensor(coordinator=entry.runtime_data),
        Pv2VoltageSensor(coordinator=entry.runtime_data),
        Pv2CurrentSensor(coordinator=entry.runtime_data),
        BatteryVoltageSensor(coordinator=entry.runtime_data),
        BatteryCurrentSensor(coordinator=entry.runtime_data),
        
        # === TEMPERATURE ===
        InverterTempSensor(coordinator=entry.runtime_data),
        DcdcTempSensor(coordinator=entry.runtime_data),
        
        # === BATTERY HEALTH ===
        BatterySohSensor(coordinator=entry.runtime_data),
        BatteryStatusTextSensor(coordinator=entry.runtime_data),
        BatteryStatusCodeSensor(coordinator=entry.runtime_data),
        
        # === CT/METER POWER ===
        Ct1PowerSensor(coordinator=entry.runtime_data),
        Ct2PowerSensor(coordinator=entry.runtime_data),
        MeterPowerSensor(coordinator=entry.runtime_data),
        
        # === ENERGY FLOW (App Display) ===
        EnergyFlowPvSensor(coordinator=entry.runtime_data),
        EnergyFlowBattSensor(coordinator=entry.runtime_data),
        EnergyFlowGridSensor(coordinator=entry.runtime_data),
        EnergyFlowLoadSensor(coordinator=entry.runtime_data),
        
        # === SYSTEM INFO ===
        RatedPowerSensor(coordinator=entry.runtime_data),
        SystemModeSensor(coordinator=entry.runtime_data),
        SystemStatusSensor(coordinator=entry.runtime_data),
    ]
    
    async_add_entities(entities)
    _LOGGER.info("Added %d ESY Sunhome sensors", len(entities))


class EsySensorBase(EsySunhomeEntity, SensorEntity):
    """Base class for ESY Sunhome sensors."""

    _attr_key: str = ""

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.data and hasattr(self.coordinator.data, self._attr_key):
            self._attr_native_value = getattr(self.coordinator.data, self._attr_key, None)
        elif self.coordinator.data and isinstance(self.coordinator.data, dict):
            self._attr_native_value = self.coordinator.data.get(self._attr_key)
        self.async_write_ha_state()


# =============================================================================
# CORE POWER SENSORS
# =============================================================================

class StateOfChargeSensor(EsySensorBase):
    """Battery State of Charge."""
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = ATTR_SOC
    _attr_key = "batterySoc"
    _attr_icon = "mdi:battery"


class EsyPowerSensor(EsySensorBase):
    """Base class for power sensors."""
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT


class PvPowerSensor(EsyPowerSensor):
    """Total PV Power."""
    _attr_translation_key = ATTR_PV_POWER
    _attr_key = "pvPower"
    _attr_icon = "mdi:solar-power-variant"


class Pv1PowerSensor(EsyPowerSensor):
    """PV String 1 Power."""
    _attr_translation_key = ATTR_PV1_POWER
    _attr_key = "pv1Power"
    _attr_icon = "mdi:solar-panel"
    _attr_entity_registry_enabled_default = False


class Pv2PowerSensor(EsyPowerSensor):
    """PV String 2 Power."""
    _attr_translation_key = ATTR_PV2_POWER
    _attr_key = "pv2Power"
    _attr_icon = "mdi:solar-panel"
    _attr_entity_registry_enabled_default = False


class DcPvPowerSensor(EsyPowerSensor):
    """DC PV Power (ESY PV - panels connected to inverter DC inputs)."""
    _attr_translation_key = "dc_pv_power"
    _attr_key = "dcPvPower"
    _attr_icon = "mdi:solar-panel"
    _attr_entity_registry_enabled_default = False


class AcPvPowerSensor(EsyPowerSensor):
    """AC PV Power (AC-coupled solar measured by CT2)."""
    _attr_translation_key = "ac_pv_power"
    _attr_key = "acPvPower"
    _attr_icon = "mdi:solar-panel-large"
    _attr_entity_registry_enabled_default = False


class GridPowerSensor(EsyPowerSensor):
    """Grid Power (+ import, - export)."""
    _attr_translation_key = ATTR_GRID_POWER
    _attr_key = "gridPower"
    _attr_icon = "mdi:transmission-tower"


class LoadPowerSensor(EsyPowerSensor):
    """Load/Consumption Power."""
    _attr_translation_key = ATTR_LOAD_POWER
    _attr_key = "loadPower"
    _attr_icon = "mdi:home-lightning-bolt"


class BatteryPowerSensor(EsyPowerSensor):
    """Battery Power (+ charging, - discharging)."""
    _attr_translation_key = ATTR_BATTERY_POWER
    _attr_key = "batteryPower"
    _attr_icon = "mdi:battery-charging"


# =============================================================================
# DIRECTIONAL POWER SENSORS
# =============================================================================

class BatteryImportSensor(EsyPowerSensor):
    """Battery Charging Power."""
    _attr_translation_key = ATTR_BATTERY_IMPORT
    _attr_key = "batteryImport"
    _attr_icon = "mdi:battery-arrow-up"


class BatteryExportSensor(EsyPowerSensor):
    """Battery Discharging Power."""
    _attr_translation_key = ATTR_BATTERY_EXPORT
    _attr_key = "batteryExport"
    _attr_icon = "mdi:battery-arrow-down"


class GridImportSensor(EsyPowerSensor):
    """Grid Import Power."""
    _attr_translation_key = ATTR_GRID_IMPORT
    _attr_key = "gridImport"
    _attr_icon = "mdi:transmission-tower-import"


class GridExportSensor(EsyPowerSensor):
    """Grid Export Power."""
    _attr_translation_key = ATTR_GRID_EXPORT
    _attr_key = "gridExport"
    _attr_icon = "mdi:transmission-tower-export"


# =============================================================================
# ENERGY SENSORS (kWh)
# =============================================================================

class EsyEnergySensor(EsySensorBase):
    """Base class for energy sensors."""
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING


class DailyPowerGenSensor(EsyEnergySensor):
    """Daily Power Generation."""
    _attr_translation_key = ATTR_DAILY_POWER_GEN
    _attr_key = "dailyPowerGeneration"
    _attr_icon = "mdi:solar-power"
    _attr_state_class = SensorStateClass.TOTAL


class DailyConsumptionSensor(EsyEnergySensor):
    """Daily Power Consumption."""
    _attr_translation_key = ATTR_DAILY_CONSUMPTION
    _attr_key = "dailyConsumption"
    _attr_icon = "mdi:home-lightning-bolt-outline"
    _attr_state_class = SensorStateClass.TOTAL


class DailyGridExportSensor(EsyEnergySensor):
    """Daily Grid Export."""
    _attr_translation_key = ATTR_DAILY_GRID_EXPORT
    _attr_key = "dailyGridExport"
    _attr_icon = "mdi:transmission-tower-export"
    _attr_state_class = SensorStateClass.TOTAL


class DailyBattChargeSensor(EsyEnergySensor):
    """Daily Battery Charge Energy."""
    _attr_translation_key = ATTR_DAILY_BATT_CHARGE
    _attr_key = "dailyBattCharge"
    _attr_icon = "mdi:battery-plus"
    _attr_state_class = SensorStateClass.TOTAL


class DailyBattDischargeSensor(EsyEnergySensor):
    """Daily Battery Discharge Energy."""
    _attr_translation_key = ATTR_DAILY_BATT_DISCHARGE
    _attr_key = "dailyBattDischarge"
    _attr_icon = "mdi:battery-minus"
    _attr_state_class = SensorStateClass.TOTAL


class TotalPowerGenSensor(EsyEnergySensor):
    """Total Power Generation."""
    _attr_translation_key = ATTR_TOTAL_POWER_GEN
    _attr_key = "totalPowerGeneration"
    _attr_icon = "mdi:counter"


# =============================================================================
# VOLTAGE & CURRENT SENSORS
# =============================================================================

class EsyVoltageSensor(EsySensorBase):
    """Base class for voltage sensors."""
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT


class EsyCurrentSensor(EsySensorBase):
    """Base class for current sensors."""
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_state_class = SensorStateClass.MEASUREMENT


class GridVoltageSensor(EsyVoltageSensor):
    """Grid Voltage."""
    _attr_translation_key = ATTR_GRID_VOLTAGE
    _attr_key = "gridVoltage"
    _attr_icon = "mdi:flash"


class GridFrequencySensor(EsySensorBase):
    """Grid Frequency."""
    _attr_device_class = SensorDeviceClass.FREQUENCY
    _attr_native_unit_of_measurement = UnitOfFrequency.HERTZ
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = ATTR_GRID_FREQUENCY
    _attr_key = "gridFrequency"
    _attr_icon = "mdi:sine-wave"


class Pv1VoltageSensor(EsyVoltageSensor):
    """PV String 1 Voltage."""
    _attr_translation_key = ATTR_PV1_VOLTAGE
    _attr_key = "pv1Voltage"
    _attr_icon = "mdi:solar-panel"
    _attr_entity_registry_enabled_default = False


class Pv1CurrentSensor(EsyCurrentSensor):
    """PV String 1 Current."""
    _attr_translation_key = ATTR_PV1_CURRENT
    _attr_key = "pv1Current"
    _attr_icon = "mdi:solar-panel"
    _attr_entity_registry_enabled_default = False


class Pv2VoltageSensor(EsyVoltageSensor):
    """PV String 2 Voltage."""
    _attr_translation_key = ATTR_PV2_VOLTAGE
    _attr_key = "pv2Voltage"
    _attr_icon = "mdi:solar-panel"
    _attr_entity_registry_enabled_default = False


class Pv2CurrentSensor(EsyCurrentSensor):
    """PV String 2 Current."""
    _attr_translation_key = ATTR_PV2_CURRENT
    _attr_key = "pv2Current"
    _attr_icon = "mdi:solar-panel"
    _attr_entity_registry_enabled_default = False


class BatteryVoltageSensor(EsyVoltageSensor):
    """Battery Voltage."""
    _attr_translation_key = ATTR_BATTERY_VOLTAGE
    _attr_key = "batteryVoltage"
    _attr_icon = "mdi:battery"
    _attr_entity_registry_enabled_default = False


class BatteryCurrentSensor(EsyCurrentSensor):
    """Battery Current."""
    _attr_translation_key = ATTR_BATTERY_CURRENT
    _attr_key = "batteryCurrent"
    _attr_icon = "mdi:battery"
    _attr_entity_registry_enabled_default = False


# =============================================================================
# TEMPERATURE SENSORS
# =============================================================================

class EsyTempSensor(EsySensorBase):
    """Base class for temperature sensors."""
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT


class InverterTempSensor(EsyTempSensor):
    """Inverter Temperature."""
    _attr_translation_key = ATTR_INVERTER_TEMP
    _attr_key = "inverterTemp"
    _attr_icon = "mdi:thermometer"


class DcdcTempSensor(EsyTempSensor):
    """DC-DC Converter Temperature."""
    _attr_translation_key = ATTR_DCDC_TEMP
    _attr_key = "dcdcTemperature"
    _attr_icon = "mdi:thermometer"
    _attr_entity_registry_enabled_default = False


# =============================================================================
# BATTERY HEALTH SENSORS
# =============================================================================

class BatterySohSensor(EsySensorBase):
    """Battery State of Health."""
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = ATTR_BATTERY_SOH
    _attr_key = "batterySoh"
    _attr_icon = "mdi:battery-heart"
    _attr_entity_registry_enabled_default = False


class BatteryStatusTextSensor(EsySensorBase):
    """Battery Status Text."""
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_translation_key = ATTR_BATTERY_STATUS_TEXT
    _attr_key = "batteryStatusText"
    _attr_icon = "mdi:battery-clock"
    _attr_options = ["Standby", "Charging", "Charge Topping", "Float Charge", "Full", "Discharging", "Unknown"]


class BatteryStatusCodeSensor(EsySensorBase):
    """Battery Status Code (0=Standby, 1=Charging, 2=Charge Topping, 3=Float Charge, 4=Full, 5=Discharging)."""
    _attr_translation_key = "battery_status_code"
    _attr_key = "batteryStatus"
    _attr_icon = "mdi:battery-sync"
    _attr_entity_registry_enabled_default = False


# =============================================================================
# CT/METER SENSORS
# =============================================================================

class Ct1PowerSensor(EsyPowerSensor):
    """CT1 Power (Grid Meter)."""
    _attr_translation_key = ATTR_CT1_POWER
    _attr_key = "ct1Power"
    _attr_icon = "mdi:current-ac"
    _attr_entity_registry_enabled_default = False


class Ct2PowerSensor(EsyPowerSensor):
    """CT2 Power."""
    _attr_translation_key = ATTR_CT2_POWER
    _attr_key = "ct2Power"
    _attr_icon = "mdi:current-ac"
    _attr_entity_registry_enabled_default = False


class MeterPowerSensor(EsyPowerSensor):
    """Smart Meter Power."""
    _attr_translation_key = ATTR_METER_POWER
    _attr_key = "meterPower"
    _attr_icon = "mdi:meter-electric"
    _attr_entity_registry_enabled_default = False


# =============================================================================
# ENERGY FLOW SENSORS (App Display)
# =============================================================================

class EnergyFlowPvSensor(EsyPowerSensor):
    """Energy Flow - PV (App Display)."""
    _attr_translation_key = ATTR_ENERGY_FLOW_PV
    _attr_key = "energyFlowPv"
    _attr_icon = "mdi:solar-power"
    _attr_entity_registry_enabled_default = False


class EnergyFlowBattSensor(EsyPowerSensor):
    """Energy Flow - Battery (App Display)."""
    _attr_translation_key = ATTR_ENERGY_FLOW_BATT
    _attr_key = "energyFlowBatt"
    _attr_icon = "mdi:battery-outline"
    _attr_entity_registry_enabled_default = False


class EnergyFlowGridSensor(EsyPowerSensor):
    """Energy Flow - Grid (App Display)."""
    _attr_translation_key = ATTR_ENERGY_FLOW_GRID
    _attr_key = "energyFlowGrid"
    _attr_icon = "mdi:transmission-tower"
    _attr_entity_registry_enabled_default = False


class EnergyFlowLoadSensor(EsyPowerSensor):
    """Energy Flow - Load (App Display)."""
    _attr_translation_key = ATTR_ENERGY_FLOW_LOAD
    _attr_key = "energyFlowLoad"
    _attr_icon = "mdi:home-lightning-bolt"
    _attr_entity_registry_enabled_default = False


# =============================================================================
# SYSTEM INFO SENSORS
# =============================================================================

class RatedPowerSensor(EsyPowerSensor):
    """Inverter Rated Power."""
    _attr_translation_key = ATTR_RATED_POWER
    _attr_key = "ratedPower"
    _attr_icon = "mdi:lightning-bolt"
    _attr_entity_registry_enabled_default = False


class SystemModeSensor(EsySensorBase):
    """System Run Mode."""
    _attr_translation_key = ATTR_SYSTEM_RUN_MODE
    _attr_key = "systemRunMode"
    _attr_icon = "mdi:cog"
    _attr_entity_registry_enabled_default = False


class SystemStatusSensor(EsySensorBase):
    """System Run Status."""
    _attr_translation_key = ATTR_SYSTEM_RUN_STATUS
    _attr_key = "systemRunStatus"
    _attr_icon = "mdi:information"
    _attr_entity_registry_enabled_default = False

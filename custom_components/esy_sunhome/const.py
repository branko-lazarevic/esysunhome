"""Constants for ESY Sunhome integration."""

DOMAIN = "esy_sunhome"

# API Endpoints
ESY_API_BASE_URL = "http://esybackend.esysunhome.com:7073"
ESY_API_LOGIN_ENDPOINT = "/login?grant_type=app"
ESY_API_DEVICE_ENDPOINT = "/api/lsydevice/page?current=1&size=10"
ESY_API_OBTAIN_ENDPOINT = "/api/param/set/obtain?val=3&deviceId="
ESY_API_MODE_ENDPOINT = "/api/lsypattern/switch"
ESY_SCHEDULES_ENDPOINT = "/api/lsydevicechargedischarge/info?deviceId="

# Protocol API Endpoints (for dynamic register loading)
ESY_API_PROTOCOL_LIST = "/sys/protocol/list"
ESY_API_PROTOCOL_SEGMENT = "/sys/protocol/segment"

# Device Info and Certificate Endpoints
ESY_API_DEVICE_INFO = "/api/lsydevice/info"
ESY_API_CERT_ENDPOINT = "/security/cert/android"

# MQTT Configuration (TLS on port 8883)
ESY_MQTT_BROKER_URL = "abroadtcp.esysunhome.com"
ESY_MQTT_BROKER_PORT = 8883

# Fallback MQTT credentials (if device info not available)
ESY_MQTT_USERNAME = "admin"
ESY_MQTT_PASSWORD = "3omKSLaDI7q27OhX"

# Config Keys
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_SN = "device_sn"
CONF_ENABLE_POLLING = "enable_polling"
CONF_PV_POWER = "pv_power"
CONF_TP_TYPE = "tp_type"
CONF_MCU_VERSION = "mcu_version"

# Attribute Keys
ATTR_DEVICE_ID = "deviceId"

DEFAULT_ENABLE_POLLING = True
DEFAULT_PV_POWER = 6
DEFAULT_TP_TYPE = 1
DEFAULT_MCU_VERSION = 1049

# Core Power Sensors
ATTR_SOC = "batterySoc"
ATTR_GRID_POWER = "gridPower"
ATTR_LOAD_POWER = "loadPower"
ATTR_BATTERY_POWER = "batteryPower"
ATTR_PV_POWER = "pvPower"
ATTR_PV1_POWER = "pv1Power"
ATTR_PV2_POWER = "pv2Power"

# Directional Power (derived)
ATTR_BATTERY_IMPORT = "batteryImport"
ATTR_BATTERY_EXPORT = "batteryExport"
ATTR_GRID_IMPORT = "gridImport"
ATTR_GRID_EXPORT = "gridExport"

# Binary Status
ATTR_GRID_ACTIVE = "gridLine"
ATTR_LOAD_ACTIVE = "loadLine"
ATTR_PV_ACTIVE = "pvLine"
ATTR_BATTERY_ACTIVE = "batteryLine"

# System Status
ATTR_SCHEDULE_MODE = "code"
ATTR_HEATER_STATE = "heatingState"
ATTR_BATTERY_STATUS = "batteryStatus"
ATTR_BATTERY_STATUS_TEXT = "batteryStatusText"
ATTR_SYSTEM_RUN_MODE = "systemRunMode"
ATTR_SYSTEM_RUN_STATUS = "systemRunStatus"
ATTR_ON_OFF_GRID_MODE = "onOffGridMode"

# Energy Statistics (Daily)
ATTR_DAILY_POWER_GEN = "dailyPowerGeneration"
ATTR_DAILY_CONSUMPTION = "dailyPowerConsumption"
ATTR_DAILY_GRID_IMPORT = "dailyGridImport"
ATTR_DAILY_GRID_EXPORT = "dailyGridExport"
ATTR_DAILY_BATT_CHARGE = "dailyBattCharge"
ATTR_DAILY_BATT_DISCHARGE = "dailyBattDischarge"
ATTR_DAILY_SELF_USE = "dailySelfUse"

# Energy Statistics (Total)
ATTR_TOTAL_POWER_GEN = "totalPowerGeneration"
ATTR_TOTAL_CONSUMPTION = "totalConsumption"
ATTR_TOTAL_GRID_IMPORT = "totalGridImport"
ATTR_TOTAL_GRID_EXPORT = "totalGridExport"
ATTR_TOTAL_BATT_CHARGE = "totalBattCharge"
ATTR_TOTAL_BATT_DISCHARGE = "totalBattDischarge"

# Voltage & Current
ATTR_GRID_VOLTAGE = "gridVoltage"
ATTR_GRID_FREQUENCY = "gridFrequency"
ATTR_PV1_VOLTAGE = "pv1Voltage"
ATTR_PV1_CURRENT = "pv1Current"
ATTR_PV2_VOLTAGE = "pv2Voltage"
ATTR_PV2_CURRENT = "pv2Current"
ATTR_BATTERY_VOLTAGE = "batteryVoltage"
ATTR_BATTERY_CURRENT = "batteryCurrent"
ATTR_LOAD_VOLTAGE = "loadVoltage"
ATTR_LOAD_CURRENT = "loadCurrent"

# Temperature
ATTR_INVERTER_TEMP = "inverterTemp"
ATTR_DCDC_TEMP = "dcdcTemperature"
ATTR_BATTERY_TEMP = "batteryTemp"

# Battery Extended
ATTR_BATTERY_SOH = "batterySoh"
ATTR_BATTERY_CYCLES = "batteryCycles"
ATTR_BATTERY_CAPACITY = "batteryCapacity"
ATTR_BATT_CELL_MAX = "battCellVoltMax"
ATTR_BATT_CELL_MIN = "battCellVoltMin"

# System Info
ATTR_RATED_POWER = "ratedPower"
ATTR_MCU_VERSION = "mcuVersion"
ATTR_DSP_VERSION = "dspVersion"
ATTR_DEVICE_TYPE = "deviceType"

# CT/Meter Power
ATTR_CT1_POWER = "ct1Power"
ATTR_CT2_POWER = "ct2Power"
ATTR_METER_POWER = "meterPower"

# Energy Flow (from app display)
ATTR_ENERGY_FLOW_PV = "energyFlowPv"
ATTR_ENERGY_FLOW_BATT = "energyFlowBatt"
ATTR_ENERGY_FLOW_GRID = "energyFlowGrid"
ATTR_ENERGY_FLOW_LOAD = "energyFlowLoad"

# Percentages
ATTR_SELF_SUFFICIENCY = "selfSufficiencyPercent"
ATTR_SELF_USE_PERCENT = "selfUsePercent"

# Protocol Data Types
DATA_TYPE_UNSIGNED = "unsigned"
DATA_TYPE_SIGNED = "signed"

# Modbus Function Codes
FC_READ_COILS = 1
FC_READ_DISCRETE = 2
FC_READ_HOLDING = 3
FC_READ_INPUT = 4

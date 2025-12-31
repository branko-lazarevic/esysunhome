"""Constants for the ESY Sunhome integration."""

DOMAIN = "esy_sunhome"

# API Configuration
ESY_API_BASE_URL = "http://esybackend.esysunhome.com:7073"
ESY_API_LOGIN_ENDPOINT = "/login?grant_type=app"
ESY_API_DEVICE_ENDPOINT = "/api/lsydevice/page?current=1&size=1"
ESY_API_OBTAIN_ENDPOINT = "/api/param/set/obtain?val=3&deviceId="
ESY_API_MODE_ENDPOINT = "/api/lsypattern/switch"
ESY_SCHEDULES_ENDPOINT = "/api/lsydevicechargedischarge/info?deviceId="

# MQTT Configuration - v2.0.0 binary protocol
ESY_MQTT_BROKER_URL = "abroadtcp.esysunhome.com"
ESY_MQTT_BROKER_PORT = 1883
# MQTT broker credentials (hardcoded in APK - same for all users)
ESY_MQTT_USERNAME = "admin"
ESY_MQTT_PASSWORD = "3omKSLaDI7q27OhX"

# MQTT Topics (v2.0.0 - binary protocol)
# Telemetry FROM inverter: /ESY/PVVC/{device_id}/UP
# Commands TO inverter: /ESY/PVVC/{device_id}/DOWN
# Alarm messages: /ESY/PVVC/{device_id}/ALARM
# Push notifications: /APP/{user_id}/NEWS

# Configuration keys
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_DEVICE_ID = "device_id"
CONF_USER_ID = "user_id"
CONF_ENABLE_POLLING = "enable_polling"
DEFAULT_ENABLE_POLLING = True

# Device attributes - existing (for backwards compatibility)
ATTR_DEVICE_ID = "deviceId"
ATTR_SOC = "batterySoc"
ATTR_GRID_POWER = "gridPower"
ATTR_LOAD_POWER = "loadPower"
ATTR_BATTERY_POWER = "batteryPower"
ATTR_PV_POWER = "pvPower"
ATTR_BATTERY_IMPORT = "batteryImport"
ATTR_BATTERY_EXPORT = "batteryExport"
ATTR_GRID_IMPORT = "gridImport"
ATTR_GRID_EXPORT = "gridExport"
ATTR_GRID_ACTIVE = "gridLine"
ATTR_LOAD_ACTIVE = "loadLine"
ATTR_PV_ACTIVE = "pvLine"
ATTR_BATTERY_ACTIVE = "batteryLine"
ATTR_SCHEDULE_MODE = "code"
ATTR_HEATER_STATE = "heatingState"
ATTR_BATTERY_STATUS = "batteryStatus"
ATTR_SYSTEM_RUN_STATUS = "systemRunStatus"
ATTR_DAILY_POWER_GEN = "dailyPowerGeneration"
ATTR_RATED_POWER = "ratedPower"
ATTR_INVERTER_TEMP = "inverterTemp"
ATTR_BATTERY_STATUS_TEXT = "batteryStatusText"

# New v2.0.0 sensor attributes
ATTR_PV1_POWER = "pv1Power"
ATTR_PV2_POWER = "pv2Power"
ATTR_PV1_VOLTAGE = "pv1Voltage"
ATTR_PV1_CURRENT = "pv1Current"
ATTR_PV2_VOLTAGE = "pv2Voltage"
ATTR_PV2_CURRENT = "pv2Current"
ATTR_BATTERY_VOLTAGE = "batteryVoltage"
ATTR_BATTERY_CURRENT = "batteryCurrent"
ATTR_GRID_VOLTAGE = "gridVoltage"
ATTR_GRID_FREQUENCY = "gridFrequency"
ATTR_INV_OUTPUT_VOLTAGE = "invOutputVoltage"
ATTR_INV_OUTPUT_FREQUENCY = "invOutputFrequency"
ATTR_TOTAL_ENERGY_GEN = "totalEnergyGeneration"
ATTR_DAILY_POWER_CONSUMPTION = "dailyPowerConsumption"
ATTR_TOTAL_POWER_CONSUMPTION = "totalPowerConsumption"
ATTR_DAILY_BATT_CHARGE = "dailyBattChargeEnergy"
ATTR_DAILY_BATT_DISCHARGE = "dailyBattDischargeEnergy"
ATTR_DAILY_GRID_IMPORT_ENERGY = "dailyGridImportEnergy"
ATTR_DAILY_GRID_EXPORT_ENERGY = "dailyGridExportEnergy"
ATTR_ON_OFF_GRID_MODE = "onOffGridMode"
ATTR_SYSTEM_RUN_MODE = "systemRunMode"
ATTR_CT1_POWER = "ct1Power"
ATTR_CT2_POWER = "ct2Power"
ATTR_ANTI_BACKFLOW_PERCENTAGE = "antiBackflowPowerPercentage"

# System run modes
SYSTEM_RUN_MODES = {
    1: "Regular Mode",
    2: "Emergency Mode",
    3: "Electricity Sell Mode",
    5: "Battery Energy Management",
}

# Battery status mapping
BATTERY_STATUS_MAP = {
    0: "Idle",
    1: "Charging",
    5: "In Use",
}

# Grid mode mapping
GRID_MODE_MAP = {
    0: "Off-Grid",
    1: "On-Grid",
}

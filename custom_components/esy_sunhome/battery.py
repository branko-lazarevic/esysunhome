"""ESY Sunhome Battery Controller - Binary Protocol Version.

Uses binary MQTT protocol on /ESY/PVVC/{device_sn}/UP for real-time data.
API calls still used for mode changes and triggering updates.
"""

import asyncio
import contextlib
import json
import logging
from typing import Any, Optional

import aiomqtt

from .esysunhome import ESYSunhomeAPI
from .protocol import ESYTelemetryParser, parse_telemetry
from .const import (
    ATTR_DEVICE_ID,
    ATTR_SOC,
    ATTR_GRID_POWER,
    ATTR_LOAD_POWER,
    ATTR_BATTERY_POWER,
    ATTR_PV_POWER,
    ATTR_BATTERY_IMPORT,
    ATTR_BATTERY_EXPORT,
    ATTR_GRID_IMPORT,
    ATTR_GRID_EXPORT,
    ATTR_GRID_ACTIVE,
    ATTR_LOAD_ACTIVE,
    ATTR_PV_ACTIVE,
    ATTR_BATTERY_ACTIVE,
    ATTR_SCHEDULE_MODE,
    ATTR_HEATER_STATE,
    ATTR_BATTERY_STATUS,
    ATTR_SYSTEM_RUN_STATUS,
    ATTR_DAILY_POWER_GEN,
    ATTR_RATED_POWER,
    ATTR_INVERTER_TEMP,
    ATTR_BATTERY_STATUS_TEXT,
    ESY_MQTT_BROKER_URL,
    ESY_MQTT_BROKER_PORT,
)

_LOGGER = logging.getLogger(__name__)

ESY_MQTT_USERNAME = ""
ESY_MQTT_PASSWORD = ""


class BatteryState:
    """Represents the current system state - compatible with legacy sensors."""

    # Mode mapping: MQTT systemRunMode value -> Display Name
    #
    # 1. MQTT systemRunMode -> display code (via EnergyFlowOptimize.e())
    # 2. display code -> mode name string (via setModeType())
    #
    # MQTT systemRunMode values to write for each mode:
    # Regular Mode = 1, Emergency Mode = 4, Sell Mode = 3, BEM = 5
    
    # This maps MQTT systemRunMode to display name (for READING from inverter)
    modes_from_mqtt = {
        1: "Regular Mode",           # MQTT 1 -> code 1 -> Regular
        4: "Emergency Mode",         # MQTT 4 -> code 2 -> Emergency
        3: "Electricity Sell Mode",  # MQTT 3 -> code 3 -> Sell
        5: "Battery Energy Management", # MQTT 5 -> BEM (default)
        0: "Battery Priority Mode",  # MQTT 0 -> code 6 -> Battery Priority
        2: "Grid Priority Mode",     # MQTT 2 -> code 7 -> Grid Priority
        6: "PV Mode",                # MQTT 6 -> code 9 -> PV
        7: "Forced Off Grid Mode",   # MQTT 7 -> code 10 -> Forced Off Grid
    }
    
    # This maps display name to MQTT value (for WRITING to inverter)
    # Only modes available in user's app (Regular, Emergency, Sell, BEM)
    modes_to_mqtt = {
        "Regular Mode": 1,
        "Emergency Mode": 4,
        "Electricity Sell Mode": 3,
        "Battery Energy Management": 5,
    }
    
    # For the HA dropdown - simple dict of available modes
    modes = {
        1: "Regular Mode",
        2: "Emergency Mode",
        3: "Electricity Sell Mode",
        4: "Battery Energy Management",
    }

    def __init__(self, data: dict) -> None:
        """Initialize with parsed telemetry data."""
        self.data = data

    def __getattr__(self, name: str):
        """Return attribute from parsed data, matching legacy naming."""
        try:
            # Special handling for mode - ALWAYS return mode name string
            # This is needed because select entity expects the mode name, not code
            if name == "code" or name == ATTR_SCHEDULE_MODE:
                mode_code = self.data.get("code", 1)
                if isinstance(mode_code, int):
                    return self.modes.get(mode_code, f"Unknown Mode ({mode_code})")
                return mode_code
            
            # Direct key lookup
            if name in self.data:
                return self.data[name]
            
            # Legacy attribute name mappings
            legacy_map = {
                ATTR_SOC: "batterySoc",
                ATTR_GRID_POWER: "gridPower",
                ATTR_LOAD_POWER: "loadPower",
                ATTR_BATTERY_POWER: "batteryPower",
                ATTR_PV_POWER: "pvPower",
                ATTR_BATTERY_IMPORT: "batteryImport",
                ATTR_BATTERY_EXPORT: "batteryExport",
                ATTR_GRID_IMPORT: "gridImport",
                ATTR_GRID_EXPORT: "gridExport",
                ATTR_GRID_ACTIVE: "gridLine",
                ATTR_LOAD_ACTIVE: "loadLine",
                ATTR_PV_ACTIVE: "pvLine",
                ATTR_BATTERY_ACTIVE: "batteryLine",
                ATTR_HEATER_STATE: "heatingState",
                ATTR_BATTERY_STATUS: "batteryStatus",
                ATTR_SYSTEM_RUN_STATUS: "systemRunStatus",
                ATTR_DAILY_POWER_GEN: "dailyPowerGeneration",
                ATTR_RATED_POWER: "ratedPower",
                ATTR_INVERTER_TEMP: "inverterTemp",
                ATTR_BATTERY_STATUS_TEXT: "batteryStatusText",
            }
            
            mapped_key = legacy_map.get(name, name)
            if mapped_key in self.data:
                return self.data[mapped_key]
            
            raise AttributeError(f"Attribute '{name}' not found in data")
            
        except (IndexError, KeyError) as e:
            raise AttributeError(f"Attribute '{name}' not found") from e


class MessageListener:
    """Message Listener interface."""

    def on_message(self, state: BatteryState) -> None:
        """Handle incoming messages."""
        pass


class EsySunhomeBattery:
    """EsySunhome Battery Controller using binary MQTT protocol."""

    def __init__(
        self,
        username: str,
        password: str,
        device_id: str,
        device_sn: str = None,
    ) -> None:
        """Initialize.
        
        Args:
            username: ESY account username
            password: ESY account password  
            device_id: Device ID (numeric)
            device_sn: Device serial number (for MQTT topic, defaults to device_id)
        """
        self.username = username
        self.password = password
        self.device_id = device_id
        self.device_sn = device_sn or device_id
        
        # Binary protocol topic
        self.subscribe_topic = f"/ESY/PVVC/{self.device_sn}/UP"
        
        self.api = None
        self.parser = ESYTelemetryParser()
        
        self._client = None
        self._connected = False
        self._listener_task = None
        self._last_state: Optional[BatteryState] = None

    async def request_api_update(self):
        """Trigger the API call to publish data."""
        if not self.api:
            self.api = ESYSunhomeAPI(self.username, self.password, self.device_id)
        await self.api.request_update()

    def connect(self, listener: MessageListener) -> None:
        """Connect to MQTT server and subscribe for updates."""
        self._listener_task = asyncio.create_task(self._listen(listener))

    async def _listen(self, listener: MessageListener):
        """Main MQTT listening loop."""
        self._connected = True
        
        while self._connected:
            try:
                _LOGGER.info(
                    "Connecting to MQTT broker %s:%d (topic: %s)",
                    ESY_MQTT_BROKER_URL,
                    ESY_MQTT_BROKER_PORT,
                    self.subscribe_topic
                )
                
                async with aiomqtt.Client(
                    hostname=ESY_MQTT_BROKER_URL,
                    port=ESY_MQTT_BROKER_PORT,
                    username=ESY_MQTT_USERNAME,
                    password=ESY_MQTT_PASSWORD,
                ) as self._client:
                    _LOGGER.info("Connected, subscribing to %s", self.subscribe_topic)
                    await self._client.subscribe(self.subscribe_topic)

                    # Request initial update
                    await self.request_api_update()

                    # Process messages
                    async for message in self._client.messages:
                        self._process_message(message, listener)

            except aiomqtt.MqttError as mqtt_err:
                _LOGGER.warning("MQTT error, will retry in 5s: %s", mqtt_err)
                self._client = None
            except asyncio.CancelledError:
                _LOGGER.debug("MQTT loop cancelled")
                break
            except Exception as e:
                _LOGGER.error("Exception in MQTT loop: %s", e, exc_info=True)
            finally:
                await asyncio.sleep(5)

    async def disconnect(self) -> None:
        """Disconnect from MQTT Server."""
        if self._listener_task is None:
            return
        self._connected = False
        self._listener_task.cancel()
        try:
            await self._listener_task
        except asyncio.CancelledError:
            _LOGGER.debug("Listener cancelled")
        self._listener_task = None
        self._client = None

    def _process_message(self, message, listener: MessageListener):
        """Process incoming binary MQTT message."""
        try:
            payload = message.payload
            topic = str(message.topic)
            
            _LOGGER.debug("MQTT message received on %s (%d bytes)", topic, len(payload))
            _LOGGER.debug("=== MQTT TELEMETRY RECEIVED ===")
            _LOGGER.debug("Payload length: %d bytes", len(payload))
            _LOGGER.debug("Payload (hex): %s...", payload[:100].hex())
            
            # Parse binary payload
            data = self.parser.parse_message(payload)
            
            if data:
                state = BatteryState(data)
                self._last_state = state
                
                # Log summary
                _LOGGER.debug("=== PARSED TELEMETRY SUMMARY ===")
                _LOGGER.debug("  PV1 Power: %sW", data.get("pv1Power", "N/A"))
                _LOGGER.debug("  PV2 Power: %sW", data.get("pv2Power", "N/A"))
                _LOGGER.debug("  Battery SOC: %s%%", data.get("batterySoc", "N/A"))
                _LOGGER.debug("  Battery Power: %sW", data.get("batteryPower", "N/A"))
                _LOGGER.debug("  Battery Voltage: %sV", data.get("batteryVoltage", "N/A"))
                _LOGGER.debug("  Battery Current: %sA", data.get("batteryCurrent", "N/A"))
                _LOGGER.debug("  Grid Power: %sW", data.get("gridPower", "N/A"))
                _LOGGER.debug("  Load Power: %sW", data.get("loadPower", "N/A"))
                _LOGGER.debug("  Inverter Temp: %s°C", data.get("inverterTemp", "N/A"))
                _LOGGER.debug("  Daily Generation: %skWh", data.get("dailyPowerGeneration", "N/A"))
                _LOGGER.debug("  Grid Mode: %s", data.get("onOffGridMode", "N/A"))
                _LOGGER.debug("================================")
                
                listener.on_message(state)
            else:
                _LOGGER.warning("Failed to parse binary payload")

        except Exception as e:
            _LOGGER.error("Error processing message: %s", e, exc_info=True)

    async def request_update(self) -> None:
        """Send MQTT update request to controller."""
        await self.request_api_update()

    async def set_value(self, value_name: str, value: int) -> None:
        """Set a value via API."""
        if not self.api:
            self.api = ESYSunhomeAPI(self.username, self.password, self.device_id)

        if value_name == ATTR_SCHEDULE_MODE:
            await self.api.set_mode(value)


async def main():
    """Test harness."""
    import sys
    
    class LogListener(MessageListener):
        def on_message(self, state: BatteryState) -> None:
            print(f"SOC: {state.batterySoc}%")
            print(f"PV: {state.pvPower}W")
            print(f"Grid: {state.gridPower}W")
            print(f"Battery: {state.batteryPower}W")
            print(f"Load: {state.loadPower}W")
            print("---")

    if len(sys.argv) < 4:
        print("Usage: python battery.py <username> <password> <device_id> [device_sn]")
        return

    device_sn = sys.argv[4] if len(sys.argv) > 4 else sys.argv[3]
    
    battery = EsySunhomeBattery(
        username=sys.argv[1],
        password=sys.argv[2],
        device_id=sys.argv[3],
        device_sn=device_sn,
    )
    
    battery.connect(LogListener())
    
    try:
        while True:
            await asyncio.sleep(30)
            await battery.request_update()
    except KeyboardInterrupt:
        await battery.disconnect()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s'
    )
    asyncio.run(main())

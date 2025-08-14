import asyncio
import contextlib
import json
import logging
from typing import Any
from unicodedata import name

import aiomqtt
from .esysunhome import ESYSunhomeAPI
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


class BatteryState:
    """Represents the current system state."""

    # AI Mode isn't currently available and i don't see the other modes in the app so they're commented out for now
    modes = {
        1: "Regular Mode",
        2: "Emergency Mode",
        3: "Electricity Sell Mode",
        #4: "AI Mode",
        5: "Battery Energy Management",
        # 6: "Battery Priority Mode",
        # 7: "Grid Priority Mode",
        # 8: "AC Charging Off & Backup Mode",
        # 9: "PV Mode",
        # 10: "Forced Off-grid Mode",
    }

    attr_map = {
        ATTR_DEVICE_ID: (
            0,
            None,
            None,
        ),  # Assuming deviceId is directly returned as an integer
        ATTR_SOC: (
            1,
            lambda x: x,
            None,
        ),  # State of Charge, just return the raw value (percentage)
        ATTR_GRID_POWER: (2, lambda x: x, None),  # Grid Power, raw value (W)
        ATTR_LOAD_POWER: (3, lambda x: x, None),  # Load Power, raw value (W)
        ATTR_BATTERY_POWER: (4, lambda x: x, None),  # Battery Power, raw value (W)
        ATTR_PV_POWER: (5, lambda x: x, None),  # PV Power, raw value (W)
        ATTR_BATTERY_IMPORT: (
            6,
            lambda x: x if x > 0 else 0,
            None,
        ),  # Battery Import, 0 if value <= 0
        ATTR_BATTERY_EXPORT: (
            7,
            lambda x: x if x > 0 else 0,
            None,
        ),  # Battery Export, 0 if value <= 0
        ATTR_GRID_IMPORT: (
            8,
            lambda x: x if x > 0 else 0,
            None,
        ),  # Grid Import, 0 if value <= 0
        ATTR_GRID_EXPORT: (
            9,
            lambda x: x if x > 0 else 0,
            None,
        ),  # Grid Export, 0 if value <= 0
        ATTR_GRID_ACTIVE: (
            10,
            lambda x: x,
            None,
        ),  # Grid Active, raw value (could be 0, 1, or 2)
        ATTR_LOAD_ACTIVE: (
            11,
            lambda x: x,
            None,
        ),  # Load Active, raw value (could be 0 or 1)
        ATTR_PV_ACTIVE: (
            12,
            lambda x: x,
            None,
        ),  # PV Active, raw value (could be 0 or 1)
        ATTR_BATTERY_ACTIVE: (
            13,
            lambda x: x,
            None,
        ),  # Battery Active, raw value (could be 0 or 1)
        ATTR_SCHEDULE_MODE: (
            14,
            lambda x: BatteryState.modes.get(x, "Unknown Mode"),
            None,
        ),
        ATTR_HEATER_STATE: (
            15,
            lambda x: x,
            None,
        ),  # Heater State, raw value (N/A, 0, etc.)
        ATTR_BATTERY_STATUS: (
            16,
            lambda x: "Idle"
            if x == 0
            else "Charging"
            if x == 1
            else "In Use"
            if x == 5
            else "Unknown",
            None,
        ),  # Map battery status code
        ATTR_SYSTEM_RUN_STATUS: (
            17,
            lambda x: x,
            None,
        ),  # System Run Status, raw value (integer)
        ATTR_DAILY_POWER_GEN: (
            18,
            lambda x: x,
            None,
        ),  # Daily Power Generation, raw value (kWh)
        ATTR_RATED_POWER: (19, lambda x: x, None),  # Rated Power, raw value (kW)
        ATTR_INVERTER_TEMP: (
            20,
            lambda x: x,
            None,
        ),  # Inverter Temperature, raw value (Celsius)
        ATTR_BATTERY_STATUS_TEXT: (
            21,
            lambda x: "Idle"
            if x == 0
            else "Charging"
            if x == 1
            else "In Use"
            if x == 5
            else f"Unknown {x}",
            None,
        ),  # Battery status text mapping
    }

    def __init__(self, data: dict) -> None:
        """Initialise with mqtt data."""
        self.data = data

    def __getattr__(self, name: str):
        """Return a processed attribute."""
        try:
            if self.data["msgType"] == 0 and self.data["valType"] == 7:
                if name in [ATTR_INVERTER_TEMP]:
                    return self.data['dataList'][5]['dataList'][0]['val']
            elif self.data["msgType"] == 0 and self.data["valType"] == 0:
                if name in [
                    ATTR_GRID_IMPORT,
                    ATTR_GRID_EXPORT,
                    ATTR_BATTERY_IMPORT,
                    ATTR_BATTERY_EXPORT,
                ]:
                    if (name == ATTR_GRID_IMPORT and self.data["gridLine"] == 2) or (
                        name == ATTR_GRID_EXPORT and self.data["gridLine"] == 1
                    ):
                        return self.data[ATTR_GRID_POWER]
                    if (name == ATTR_BATTERY_IMPORT and self.data["batteryLine"] == 2) or (
                        name == ATTR_BATTERY_EXPORT and self.data["batteryLine"] == 1
                    ):
                        return self.data[ATTR_BATTERY_POWER]

                    return 0

                attr_info = self.attr_map.get(name)
                if not attr_info:
                    raise AttributeError(f"Attribute '{name}' not found in attr_map")

                raw_value = self.data[name]

                if attr_info[1]:
                    return attr_info[1](raw_value)

                return raw_value
            
            raise AttributeError(f"Attribute '{name}' not found in attr_map")
        
        except (IndexError, KeyError) as e:
            raise AttributeError from e


class MessageListener:
    """Message Listener."""

    def __init__(self, coordinator) -> None:
        """Initialise listener."""
        self.coordinator = coordinator

    def on_message(self, state: BatteryState) -> None:
        """Handle incoming messages."""
        with contextlib.suppress(AttributeError):
            self.coordinator.set_update_interval(fast=True)
        self.coordinator.async_set_updated_data(state)


class EsySunhomeBattery:
    """EsySunhome Battery Controller."""

    def __init__(self, username: str, password: str, device_id: str) -> None:
        """Initialize."""
        self.username = username
        self.password = password
        self.device_id = device_id
        self.subscribe_topic = f"/APP/{device_id}/NEWS"
        self.api = None

        self._client = None
        self._connected = False
        self._listener_task = None

    async def request_api_update(self):
        """Trigger the API call to publish data"""
        if not self.api:
            self.api = ESYSunhomeAPI(self.username, self.password, self.device_id)
        await self.api.request_update()

    def connect(self, listener: MessageListener) -> None:
        """Connect to MQTT server and subscribe for updates."""
        self._listener_task = asyncio.create_task(self._listen(listener))

    async def _listen(self, listener: MessageListener):
        loop = asyncio.get_running_loop()

        self._connected = True
        while self._connected:
            try:
                async with aiomqtt.Client(
                    hostname=ESY_MQTT_BROKER_URL, port=ESY_MQTT_BROKER_PORT
                ) as self._client:
                    _LOGGER.debug("Connected, subscribing to %s", self.subscribe_topic)

                    await self._client.subscribe(self.subscribe_topic)

                    # Request initial update if necessary
                    await self.request_api_update()

                    # process messages
                    async for message in self._client.messages:
                        self._process_message(message, listener)

            except aiomqtt.MqttError as mqtt_err:
                _LOGGER.warning("Waiting for retry, error: %s", mqtt_err)
                self._client = None
            except Exception as e:
                _LOGGER.error("Exception in MQTT loop: %s", e)
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
            _LOGGER.debug("listener is cancelled")
        self._listener_task = None
        self._client = None

    def _process_message(self, message, listener: MessageListener):
        try:
            data = json.loads(message.payload)
            val = data.get("val")
            msgType = data.get("msgType")
            valType = data.get("valType")
            if val:
                battery_data = json.loads(val)
                battery_data["msgType"] = msgType
                battery_data["valType"] = valType
                _LOGGER.debug("Received battery data: %s", battery_data)
                state = BatteryState(battery_data)
                listener.on_message(state)
            else:
                _LOGGER.warning("No valid battery data found")
        except (json.JSONDecodeError, IndexError, AttributeError) as e:
            _LOGGER.error("Error processing data(%s): %s", e, message.payload)

    async def request_update(self) -> None:
        """Send MQTT update request to controller."""
        await self.request_api_update()

    async def set_value(self, value_name: str, value: int) -> None:
        if not self.api:
            self.api = ESYSunhomeAPI(self.username, self.password, self.device_id)  

        if (value_name == ATTR_SCHEDULE_MODE):
            await self.api.set_mode(value)


async def main():
    """Test harness."""

    class LogMessageListener(MessageListener):
        def on_message(self, state: BatteryState) -> None:
            _LOGGER.info(state)

    esy_battery = EsySunhomeBattery(
	username="user@test.com",
	password="password",
        device_id=12345
    )  # Replace with your actual device ID

    await esy_battery.connect(LogMessageListener())

    while True:
        _LOGGER.debug("Requesting update")
        await esy_battery.request_update()
        await asyncio.sleep(10)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())


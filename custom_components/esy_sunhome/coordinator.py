"""ESY Sunhome Data Coordinator with Dynamic Protocol."""

import asyncio
import logging
from datetime import timedelta
from typing import Any, Optional

import aiomqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    ESY_MQTT_BROKER_URL,
    ESY_MQTT_BROKER_PORT,
    ESY_MQTT_USERNAME,
    ESY_MQTT_PASSWORD,
    CONF_ENABLE_POLLING,
    DEFAULT_ENABLE_POLLING,
)
from .esysunhome import ESYSunhomeAPI
from .protocol import DynamicTelemetryParser, create_parser
from .protocol_api import ProtocolDefinition

_LOGGER = logging.getLogger(__name__)

MQTT_RECONNECT_INTERVAL = 30
POLL_INTERVAL = timedelta(seconds=60)


class TelemetryData:
    """Container for telemetry data with attribute access."""
    
    def __init__(self, data: dict):
        self._data = data
        for key, value in data.items():
            if not key.startswith("_"):
                setattr(self, key, value)
    
    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)
    
    def __getattr__(self, name: str) -> Any:
        return self._data.get(name)
    
    def __repr__(self) -> str:
        return f"TelemetryData({self._data})"


class ESYSunhomeCoordinator(DataUpdateCoordinator):
    """Coordinator for ESY Sunhome data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: ESYSunhomeAPI,
        device_sn: str,
        config_entry: ConfigEntry,
        protocol: Optional[ProtocolDefinition] = None,
    ):
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=POLL_INTERVAL,
        )
        
        self.api = api
        self.device_sn = device_sn
        self.config_entry = config_entry
        self.protocol = protocol
        
        # Create parser with protocol
        self.parser = create_parser(protocol)
        
        # MQTT state
        self._mqtt_client: Optional[aiomqtt.Client] = None
        self._mqtt_task: Optional[asyncio.Task] = None
        self._mqtt_connected = False
        self._shutdown = False
        
        # Data state
        self._last_data: dict = {}
        
        # MQTT topics
        self._topic_up = f"/ESY/PVVC/{device_sn}/UP"
        self._topic_alarm = f"/ESY/PVVC/{device_sn}/ALARM"
        
        _LOGGER.info("Coordinator initialized for device %s", device_sn)
        _LOGGER.info("MQTT topics: UP=%s, ALARM=%s", self._topic_up, self._topic_alarm)

    async def _async_update_data(self) -> TelemetryData:
        """Fetch data from API (polling fallback)."""
        enable_polling = self.config_entry.options.get(
            CONF_ENABLE_POLLING, DEFAULT_ENABLE_POLLING
        )
        
        if enable_polling and not self._mqtt_connected:
            try:
                await self.api.request_update()
                _LOGGER.debug("Requested data update from API")
            except Exception as e:
                _LOGGER.warning("Failed to request update: %s", e)
        
        # Return cached data
        return TelemetryData(self._last_data)

    async def async_config_entry_first_refresh(self) -> None:
        """Perform first refresh and start MQTT."""
        await super().async_config_entry_first_refresh()
        
        # Start MQTT listener
        self._mqtt_task = asyncio.create_task(self._mqtt_loop())
        _LOGGER.info("Started MQTT listener task")

    async def async_shutdown(self) -> None:
        """Shutdown coordinator."""
        _LOGGER.info("Shutting down coordinator")
        self._shutdown = True
        
        if self._mqtt_task:
            self._mqtt_task.cancel()
            try:
                await self._mqtt_task
            except asyncio.CancelledError:
                pass
        
        await self.api.close_session()

    async def _mqtt_loop(self) -> None:
        """Main MQTT connection loop with reconnection."""
        while not self._shutdown:
            try:
                await self._connect_mqtt()
            except asyncio.CancelledError:
                _LOGGER.info("MQTT loop cancelled")
                break
            except Exception as e:
                _LOGGER.error("MQTT connection error: %s", e)
                self._mqtt_connected = False
            
            if not self._shutdown:
                _LOGGER.info("Reconnecting MQTT in %d seconds", MQTT_RECONNECT_INTERVAL)
                await asyncio.sleep(MQTT_RECONNECT_INTERVAL)

    async def _connect_mqtt(self) -> None:
        """Connect to MQTT broker and process messages."""
        _LOGGER.info("Connecting to MQTT broker %s:%d", ESY_MQTT_BROKER_URL, ESY_MQTT_BROKER_PORT)
        
        async with aiomqtt.Client(
            hostname=ESY_MQTT_BROKER_URL,
            port=ESY_MQTT_BROKER_PORT,
            username=ESY_MQTT_USERNAME,
            password=ESY_MQTT_PASSWORD,
            keepalive=60,
        ) as client:
            self._mqtt_client = client
            self._mqtt_connected = True
            _LOGGER.info("Connected to MQTT broker")
            
            # Subscribe to topics
            await client.subscribe(self._topic_up)
            await client.subscribe(self._topic_alarm)
            _LOGGER.info("Subscribed to topics")
            
            # Process messages
            async for message in client.messages:
                if self._shutdown:
                    break
                await self._handle_message(message)

    async def _handle_message(self, message: aiomqtt.Message) -> None:
        """Handle incoming MQTT message."""
        topic = str(message.topic)
        payload = message.payload
        
        if not isinstance(payload, bytes):
            _LOGGER.warning("Unexpected payload type: %s", type(payload))
            return
        
        _LOGGER.debug("Received message on %s (%d bytes)", topic, len(payload))
        
        if topic == self._topic_up:
            await self._process_telemetry(payload)
        elif topic == self._topic_alarm:
            await self._process_alarm(payload)

    async def _process_telemetry(self, payload: bytes) -> None:
        """Process telemetry message."""
        try:
            data = self.parser.parse_message(payload)
            
            if data:
                self._last_data = data
                self.async_set_updated_data(TelemetryData(data))
                
                _LOGGER.debug("Updated telemetry: PV=%dW, Grid=%dW, Batt=%dW, Load=%dW, SOC=%d%%",
                             data.get("pvPower", 0),
                             data.get("gridPower", 0),
                             data.get("batteryPower", 0),
                             data.get("loadPower", 0),
                             data.get("batterySoc", 0))
            else:
                _LOGGER.warning("Failed to parse telemetry")
                
        except Exception as e:
            _LOGGER.error("Error processing telemetry: %s", e)

    async def _process_alarm(self, payload: bytes) -> None:
        """Process alarm message."""
        _LOGGER.info("Received alarm message (%d bytes)", len(payload))
        # TODO: Parse alarm data
    
    async def publish_command(self, command: bytes) -> bool:
        """Publish a command to the inverter via MQTT DOWN topic.
        
        Args:
            command: Binary command bytes to send
            
        Returns:
            True if published successfully, False otherwise
        """
        if not self._mqtt_client or not self._mqtt_connected:
            _LOGGER.warning("Cannot publish command: MQTT not connected")
            return False
        
        topic_down = f"/ESY/PVVC/{self.device_sn}/DOWN"
        
        try:
            await self._mqtt_client.publish(topic_down, command)
            _LOGGER.info("Published command to %s (%d bytes)", topic_down, len(command))
            return True
        except Exception as e:
            _LOGGER.error("Failed to publish command: %s", e)
            return False
    
    async def set_mode_mqtt(self, mode_code: int) -> bool:
        """Set operating mode via MQTT command.
        
        Args:
            mode_code: Mode code (1=Regular, 2=Emergency, 3=Sell, 5=BatteryMgmt)
            
        Returns:
            True if command sent successfully
        """
        from .protocol import ESYCommandBuilder
        
        # systemRunMode is holding register 57 (from official protocol)
        SYSTEM_RUN_MODE_REGISTER = 57
        config_id = self.protocol.config_id if self.protocol else 6
        
        command = ESYCommandBuilder.build_write_command(
            config_id=config_id,
            register_address=SYSTEM_RUN_MODE_REGISTER,
            value=mode_code,
            page_index=3,
            source_id=2  # App source
        )
        
        _LOGGER.info("Sending mode change command via MQTT: mode=%d", mode_code)
        return await self.publish_command(command)
        
    def update_protocol(self, protocol: ProtocolDefinition) -> None:
        """Update the protocol definition."""
        self.protocol = protocol
        self.parser.set_protocol(protocol)
        _LOGGER.info("Protocol definition updated")

"""ESY Sunhome Data Coordinator with Dynamic Protocol."""

import asyncio
import logging
import ssl
import os
from datetime import datetime, timedelta
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
from .esysunhome import ESYSunhomeAPI, MqttCredentials
from .protocol import DynamicTelemetryParser, create_parser
from .protocol_api import ProtocolDefinition

_LOGGER = logging.getLogger(__name__)

MQTT_RECONNECT_INTERVAL = 30
POLL_INTERVAL = timedelta(seconds=15)


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
        self._mqtt_credentials: Optional[MqttCredentials] = None
        
        # Certificate directory in HA config folder
        self._cert_dir = os.path.join(hass.config.config_dir, ".storage", "esy_sunhome_certs")
        
        # Data state
        self._last_data: dict = {}
        self._last_raw_values: dict = {}  # For diagnostics
        self._last_mqtt_time: Optional[str] = None  # For diagnostics
        self._poll_msg_id: int = 0  # Incrementing message ID for poll requests
        
        # MQTT topics
        self._topic_up = f"/ESY/PVVC/{device_sn}/UP"
        self._topic_down = f"/ESY/PVVC/{device_sn}/DOWN"
        self._topic_event = f"/ESY/PVVC/{device_sn}/EVENT"
        self._topic_alarm = f"/ESY/PVVC/{device_sn}/ALARM"
        
        # Default segments to poll (same as app: 0, 1, 3, 6)
        # Segment 0: Core data (addr 0-124) - power, SOC, mode
        # Segment 1: Extended data
        # Segment 3: BMS/Battery data
        # Segment 6: Inverter/CT data
        self._poll_segments = [0, 1, 3, 6]
        
        _LOGGER.info("Coordinator initialized for device %s", device_sn)
        _LOGGER.info("MQTT topics: UP=%s, EVENT=%s, DOWN=%s", 
                    self._topic_up, self._topic_event, self._topic_down)

    async def _async_update_data(self) -> TelemetryData:
        """Fetch data via MQTT poll request or API fallback."""
        enable_polling = self.config_entry.options.get(
            CONF_ENABLE_POLLING, DEFAULT_ENABLE_POLLING
        )
        
        if enable_polling:
            if self._mqtt_connected:
                # Send MQTT poll request (like the app does)
                await self._send_poll_request()
            else:
                # Fallback to API if MQTT not connected
                try:
                    await self.api.request_update()
                    _LOGGER.debug("Requested data update from API (MQTT not connected)")
                except Exception as e:
                    _LOGGER.warning("Failed to request update from API: %s", e)
        
        # Return cached data
        return TelemetryData(self._last_data)
    
    async def _send_poll_request(self) -> bool:
        """Send MQTT poll request for segments (like the app does).
        
        This sends a DOWN message requesting specific segments,
        and the inverter responds on UP with the requested data.
        """
        from .protocol import ESYCommandBuilder
        
        if not self._mqtt_client or not self._mqtt_connected:
            return False
        
        self._poll_msg_id += 1
        
        command = ESYCommandBuilder.build_poll_request(
            segment_ids=self._poll_segments,
            msg_id=self._poll_msg_id,
        )
        
        try:
            await self._mqtt_client.publish(self._topic_down, command)
            _LOGGER.debug("Sent poll request for segments %s (msg_id=%d)", 
                         self._poll_segments, self._poll_msg_id)
            return True
        except Exception as e:
            _LOGGER.error("Failed to send poll request: %s", e)
            return False

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
        
        # Note: We keep certificates for faster reconnection next time
        # They will be refreshed if they expire or fail

    async def _mqtt_loop(self) -> None:
        """Main MQTT connection loop with reconnection."""
        connection_failures = 0
        max_failures_before_refresh = 3
        
        while not self._shutdown:
            # Fetch MQTT credentials (including certificates) if needed
            if not self._mqtt_credentials or connection_failures >= max_failures_before_refresh:
                try:
                    _LOGGER.info("Fetching MQTT credentials and certificates...")
                    self._mqtt_credentials = await self.api.get_mqtt_credentials(self._cert_dir)
                    _LOGGER.info("MQTT credentials obtained: broker=%s:%d, tls=%s, mtls=%s",
                                self._mqtt_credentials.broker_url,
                                self._mqtt_credentials.port,
                                self._mqtt_credentials.use_tls,
                                self._mqtt_credentials.client_cert_path is not None)
                    connection_failures = 0  # Reset counter after refresh
                    
                    # Small delay after fetching new credentials - server may need time to activate them
                    if self._mqtt_credentials.use_tls:
                        _LOGGER.debug("Waiting 2 seconds for credentials to activate...")
                        await asyncio.sleep(2)
                        
                except Exception as e:
                    _LOGGER.error("Failed to get MQTT credentials: %s", e)
                    # Use fallback credentials
                    self._mqtt_credentials = MqttCredentials(
                        broker_url=ESY_MQTT_BROKER_URL,
                        port=1883,  # Fallback to non-TLS port
                        username=ESY_MQTT_USERNAME,
                        password=ESY_MQTT_PASSWORD,
                        use_tls=False
                    )
            
            try:
                await self._connect_mqtt()
                connection_failures = 0  # Reset on successful connection
            except asyncio.CancelledError:
                _LOGGER.info("MQTT loop cancelled")
                break
            except Exception as e:
                _LOGGER.error("MQTT connection error: %s", e)
                self._mqtt_connected = False
                connection_failures += 1
                
                # If TLS connection keeps failing, try falling back to non-TLS
                if connection_failures == 2 and self._mqtt_credentials.use_tls:
                    _LOGGER.warning("TLS connection failed twice, trying non-TLS fallback")
                    self._mqtt_credentials = MqttCredentials(
                        broker_url=ESY_MQTT_BROKER_URL,
                        port=1883,
                        username=self._mqtt_credentials.username,
                        password=self._mqtt_credentials.password,
                        use_tls=False
                    )
            
            if not self._shutdown:
                # Shorter retry interval for first few failures
                retry_interval = 5 if connection_failures == 1 else MQTT_RECONNECT_INTERVAL
                _LOGGER.info("Reconnecting MQTT in %d seconds (failures=%d)", 
                            retry_interval, connection_failures)
                await asyncio.sleep(retry_interval)

    async def _connect_mqtt(self) -> None:
        """Connect to MQTT broker and process messages."""
        creds = self._mqtt_credentials
        
        _LOGGER.info("Connecting to MQTT broker %s:%d (tls=%s, mtls=%s)", 
                    creds.broker_url, creds.port, creds.use_tls,
                    creds.client_cert_path is not None)
        
        # Build TLS context if needed (in executor to avoid blocking)
        tls_context = None
        if creds.use_tls:
            def create_ssl_context():
                """Create SSL context - runs in executor to avoid blocking."""
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                
                # Load CA certificate if available
                if creds.ca_cert_path and os.path.exists(creds.ca_cert_path):
                    ctx.load_verify_locations(creds.ca_cert_path)
                    _LOGGER.debug("Loaded CA cert from %s", creds.ca_cert_path)
                
                # Load client certificate and key for mTLS
                if (creds.client_cert_path and creds.client_key_path and 
                    os.path.exists(creds.client_cert_path) and os.path.exists(creds.client_key_path)):
                    ctx.load_cert_chain(
                        certfile=creds.client_cert_path,
                        keyfile=creds.client_key_path
                    )
                    _LOGGER.debug("Loaded client cert from %s", creds.client_cert_path)
                
                # Don't verify hostname for this broker (common with IoT devices)
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE  # ESY's cert may not be fully valid
                return ctx
            
            tls_context = await asyncio.get_event_loop().run_in_executor(None, create_ssl_context)
        
        async with aiomqtt.Client(
            hostname=creds.broker_url,
            port=creds.port,
            username=creds.username,
            password=creds.password,
            tls_context=tls_context,
            keepalive=60,
        ) as client:
            self._mqtt_client = client
            self._mqtt_connected = True
            _LOGGER.info("Connected to MQTT broker successfully")
            
            # Subscribe to topics
            await client.subscribe(self._topic_up)
            await client.subscribe(self._topic_event)
            await client.subscribe(self._topic_alarm)
            _LOGGER.info("Subscribed to UP, EVENT, and ALARM topics")
            
            # Send initial poll request to get data immediately
            await self._send_poll_request()
            
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
        elif topic == self._topic_event:
            # EVENT contains full data dump - process same as UP
            _LOGGER.info("Received EVENT message (%d bytes) - full data dump", len(payload))
            await self._process_telemetry(payload)
        elif topic == self._topic_alarm:
            await self._process_alarm(payload)

    async def _process_telemetry(self, payload: bytes) -> None:
        """Process telemetry message."""
        try:
            data = self.parser.parse_message(payload)
            
            if data:
                self._last_data = data
                # Store raw values for diagnostics
                self._last_raw_values = dict(data)
                self._last_mqtt_time = datetime.now().isoformat()
                
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
        
        Based on MQTT traffic analysis, mode is set by writing to register 57.
        The app uses a Unix timestamp as the msg_id for write commands.
        
        IMPORTANT: The mode_code here is the MQTT register value to write,
        NOT the display code! The mapping is:
        - Regular Mode -> write 1
        - Emergency Mode -> write 4
        - Electricity Sell Mode -> write 3
        - Battery Energy Management -> write 5
        
        Args:
            mode_code: MQTT register value to write
            
        Returns:
            True if command sent successfully
        """
        import time
        from .protocol import ESYCommandBuilder
        
        # Register 57 = systemRunMode / patternMode
        MODE_REGISTER = 57
        
        # MQTT register value to display name (for logging)
        MODE_NAMES = {
            1: "Regular",
            4: "Emergency", 
            3: "Sell",
            5: "BEM",
            0: "Battery Priority",
            2: "Grid Priority",
            6: "PV",
            7: "Forced Off Grid",
        }
        
        # Use Unix timestamp as msg_id (like the app does)
        msg_id = int(time.time())
        
        command = ESYCommandBuilder.build_write_command(
            register_address=MODE_REGISTER,
            value=mode_code,
            msg_id=msg_id,
        )
        
        _LOGGER.info("Sending mode change command via MQTT: register=%d, value=%d (mode=%s), msg_id=%d",
                    MODE_REGISTER, mode_code,
                    MODE_NAMES.get(mode_code, "Unknown"), msg_id)
        
        return await self.publish_command(command)
    
    async def write_register(self, register_address: int, value: int) -> bool:
        """Write a value to a register via MQTT.
        
        Args:
            register_address: Register address to write
            value: Value to write (16-bit unsigned)
            
        Returns:
            True if command sent successfully
        """
        from .protocol import ESYCommandBuilder
        
        self._poll_msg_id += 1
        
        command = ESYCommandBuilder.build_write_command(
            register_address=register_address,
            value=value,
            msg_id=self._poll_msg_id,
        )
        
        _LOGGER.info("Writing register via MQTT: addr=%d, value=%d", register_address, value)
        return await self.publish_command(command)
    
    async def write_registers(self, writes: list) -> bool:
        """Write multiple registers via MQTT.
        
        Args:
            writes: List of (address, value) or (address, [values]) tuples
            
        Returns:
            True if command sent successfully
        """
        from .protocol import ESYCommandBuilder
        
        self._poll_msg_id += 1
        
        command = ESYCommandBuilder.build_multi_write_command(
            writes=writes,
            msg_id=self._poll_msg_id,
        )
        
        _LOGGER.info("Writing %d register(s) via MQTT", len(writes))
        return await self.publish_command(command)
        
    def update_protocol(self, protocol: ProtocolDefinition) -> None:
        """Update the protocol definition."""
        self.protocol = protocol
        self.parser.set_protocol(protocol)
        _LOGGER.info("Protocol definition updated")
    
    def set_polling_enabled(self, enabled: bool) -> None:
        """Set polling enabled state.
        
        This is called by the polling switch. The actual state is stored
        in config_entry.options, this method just logs the change and
        optionally triggers an immediate poll.
        """
        _LOGGER.info("Polling %s", "enabled" if enabled else "disabled")
        
        # If enabling polling and MQTT is connected, send an immediate poll
        if enabled and self._mqtt_connected:
            asyncio.create_task(self._send_poll_request())

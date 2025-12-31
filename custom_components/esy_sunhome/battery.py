"""ESY Sunhome Battery MQTT Client - v2.0.0 Binary Protocol."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

import aiomqtt

from .const import (
    ESY_MQTT_BROKER_URL,
    ESY_MQTT_BROKER_PORT,
    SYSTEM_RUN_MODES,
    BATTERY_STATUS_MAP,
    GRID_MODE_MAP,
)
from .protocol import (
    ESYTelemetryParser,
    ESYCommandBuilder,
    TelemetryData,
    get_mqtt_topics,
)

_LOGGER = logging.getLogger(__name__)


class InverterState:
    """Represents the current inverter state parsed from binary MQTT protocol."""

    modes = SYSTEM_RUN_MODES

    def __init__(self, telemetry: TelemetryData) -> None:
        """Initialize with parsed telemetry data."""
        self._telemetry = telemetry

    @property
    def telemetry(self) -> TelemetryData:
        """Get the raw telemetry data."""
        return self._telemetry

    # Power values
    @property
    def pv_power(self) -> int:
        """Total PV power in watts."""
        return self._telemetry.pv_power

    @property
    def pv1_power(self) -> int:
        """PV1 power in watts."""
        return self._telemetry.pv1_power

    @property
    def pv2_power(self) -> int:
        """PV2 power in watts."""
        return self._telemetry.pv2_power

    @property
    def battery_power(self) -> int:
        """Battery power in watts (positive = charging, negative = discharging)."""
        return self._telemetry.battery_power

    @property
    def grid_power(self) -> int:
        """Grid power in watts (positive = import, negative = export)."""
        return self._telemetry.grid_power

    @property
    def load_power(self) -> int:
        """Load power in watts."""
        return self._telemetry.load_power

    @property
    def ct1_power(self) -> int:
        """CT1 power in watts."""
        return self._telemetry.ct1_power

    @property
    def ct2_power(self) -> int:
        """CT2 power in watts."""
        return self._telemetry.ct2_power

    # Battery information
    @property
    def battery_soc(self) -> int:
        """Battery state of charge in percent."""
        return self._telemetry.battery_soc

    @property
    def battery_voltage(self) -> float:
        """Battery voltage in volts."""
        return self._telemetry.battery_voltage

    @property
    def battery_current(self) -> float:
        """Battery current in amps."""
        return self._telemetry.battery_current

    @property
    def battery_status(self) -> int:
        """Battery status code."""
        return self._telemetry.battery_status

    @property
    def battery_status_text(self) -> str:
        """Battery status as text."""
        return BATTERY_STATUS_MAP.get(self._telemetry.battery_status, f"Unknown ({self._telemetry.battery_status})")

    # PV details
    @property
    def pv1_voltage(self) -> float:
        """PV1 voltage in volts."""
        return self._telemetry.pv1_voltage

    @property
    def pv1_current(self) -> float:
        """PV1 current in amps."""
        return self._telemetry.pv1_current

    @property
    def pv2_voltage(self) -> float:
        """PV2 voltage in volts."""
        return self._telemetry.pv2_voltage

    @property
    def pv2_current(self) -> float:
        """PV2 current in amps."""
        return self._telemetry.pv2_current

    # Grid details
    @property
    def grid_voltage(self) -> float:
        """Grid voltage in volts."""
        return self._telemetry.grid_voltage

    @property
    def grid_frequency(self) -> float:
        """Grid frequency in Hz."""
        return self._telemetry.grid_frequency

    @property
    def grid_status(self) -> int:
        """Grid status code."""
        return self._telemetry.grid_status

    @property
    def on_off_grid_mode(self) -> int:
        """On/off grid mode (0=off-grid, 1=on-grid)."""
        return self._telemetry.on_off_grid_mode

    @property
    def on_off_grid_mode_text(self) -> str:
        """On/off grid mode as text."""
        return GRID_MODE_MAP.get(self._telemetry.on_off_grid_mode, "Unknown")

    # Inverter details
    @property
    def inv_temperature(self) -> int:
        """Inverter temperature in Celsius."""
        return self._telemetry.inv_temperature

    @property
    def inv_output_voltage(self) -> float:
        """Inverter output voltage in volts."""
        return self._telemetry.inv_output_voltage

    @property
    def inv_output_frequency(self) -> float:
        """Inverter output frequency in Hz."""
        return self._telemetry.inv_output_frequency

    @property
    def inv_status(self) -> int:
        """Inverter status code."""
        return self._telemetry.inv_status

    # System status
    @property
    def system_run_mode(self) -> int:
        """System run mode code."""
        return self._telemetry.system_run_mode

    @property
    def system_run_mode_text(self) -> str:
        """System run mode as text."""
        return SYSTEM_RUN_MODES.get(self._telemetry.system_run_mode, f"Unknown ({self._telemetry.system_run_mode})")

    @property
    def system_run_status(self) -> int:
        """System run status code."""
        return self._telemetry.system_run_status

    # Energy statistics
    @property
    def daily_energy_generation(self) -> float:
        """Daily energy generation in kWh."""
        return self._telemetry.daily_energy_generation

    @property
    def total_energy_generation(self) -> float:
        """Total energy generation in kWh."""
        return self._telemetry.total_energy_generation

    @property
    def daily_power_consumption(self) -> float:
        """Daily power consumption in kWh."""
        return self._telemetry.daily_power_consumption

    @property
    def total_power_consumption(self) -> float:
        """Total power consumption in kWh."""
        return self._telemetry.total_power_consumption

    @property
    def daily_batt_charge_energy(self) -> float:
        """Daily battery charge energy in kWh."""
        return self._telemetry.daily_batt_charge_energy

    @property
    def daily_batt_discharge_energy(self) -> float:
        """Daily battery discharge energy in kWh."""
        return self._telemetry.daily_batt_discharge_energy

    @property
    def daily_grid_import(self) -> float:
        """Daily grid import in kWh."""
        return self._telemetry.daily_grid_import

    @property
    def daily_grid_export(self) -> float:
        """Daily grid export in kWh."""
        return self._telemetry.daily_grid_export

    # Other
    @property
    def rated_power(self) -> int:
        """Rated power in watts."""
        return self._telemetry.rated_power

    @property
    def anti_backflow_percentage(self) -> int:
        """Anti-backflow power percentage."""
        return self._telemetry.anti_backflow_percentage

    @property
    def heating_state(self) -> int:
        """Heating state code."""
        return self._telemetry.heating_state

    # Computed values for backwards compatibility
    @property
    def battery_import(self) -> int:
        """Battery charging power (positive when charging)."""
        return max(0, self._telemetry.battery_power)

    @property
    def battery_export(self) -> int:
        """Battery discharging power (positive when discharging)."""
        return max(0, -self._telemetry.battery_power)

    @property
    def grid_import(self) -> int:
        """Grid import power (positive when importing)."""
        return max(0, self._telemetry.grid_power)

    @property
    def grid_export(self) -> int:
        """Grid export power (positive when exporting)."""
        return max(0, -self._telemetry.grid_power)

    # Active status flags
    @property
    def pv_active(self) -> bool:
        """Whether PV is generating power."""
        return self._telemetry.pv_power > 0

    @property
    def battery_active(self) -> bool:
        """Whether battery is active (charging or discharging)."""
        return self._telemetry.battery_power != 0

    @property
    def grid_active(self) -> bool:
        """Whether grid is active."""
        return self._telemetry.grid_status > 0 or self._telemetry.grid_power != 0

    @property
    def load_active(self) -> bool:
        """Whether load is active."""
        return self._telemetry.load_power > 0

    # For backwards compatibility - alias
    @property
    def batterySoc(self) -> int:
        """Alias for battery_soc (backwards compatibility)."""
        return self.battery_soc

    @property
    def gridPower(self) -> int:
        """Alias for grid_power (backwards compatibility)."""
        return self.grid_power

    @property
    def loadPower(self) -> int:
        """Alias for load_power (backwards compatibility)."""
        return self.load_power

    @property
    def batteryPower(self) -> int:
        """Alias for battery_power (backwards compatibility)."""
        return self.battery_power

    @property
    def pvPower(self) -> int:
        """Alias for pv_power (backwards compatibility)."""
        return self.pv_power

    @property
    def batteryImport(self) -> int:
        """Alias for battery_import (backwards compatibility)."""
        return self.battery_import

    @property
    def batteryExport(self) -> int:
        """Alias for battery_export (backwards compatibility)."""
        return self.battery_export

    @property
    def gridImport(self) -> int:
        """Alias for grid_import (backwards compatibility)."""
        return self.grid_import

    @property
    def gridExport(self) -> int:
        """Alias for grid_export (backwards compatibility)."""
        return self.grid_export

    @property
    def dailyPowerGeneration(self) -> float:
        """Alias for daily_energy_generation (backwards compatibility)."""
        return self.daily_energy_generation

    @property
    def inverterTemp(self) -> int:
        """Alias for inv_temperature (backwards compatibility)."""
        return self.inv_temperature

    @property
    def batteryStatusText(self) -> str:
        """Alias for battery_status_text (backwards compatibility)."""
        return self.battery_status_text

    @property
    def gridLine(self) -> int:
        """Grid line status for backwards compatibility."""
        # 0 = inactive, 1 = exporting, 2 = importing
        if self._telemetry.grid_power > 0:
            return 2  # Importing
        elif self._telemetry.grid_power < 0:
            return 1  # Exporting
        return 0  # Inactive

    @property
    def batteryLine(self) -> int:
        """Battery line status for backwards compatibility."""
        # 0 = inactive, 1 = discharging, 2 = charging
        if self._telemetry.battery_power > 0:
            return 2  # Charging
        elif self._telemetry.battery_power < 0:
            return 1  # Discharging
        return 0  # Inactive

    @property
    def pvLine(self) -> int:
        """PV line status for backwards compatibility."""
        return 1 if self._telemetry.pv_power > 0 else 0

    @property
    def loadLine(self) -> int:
        """Load line status for backwards compatibility."""
        return 1 if self._telemetry.load_power > 0 else 0

    @property
    def code(self) -> str:
        """Operating mode name for backwards compatibility."""
        return self.system_run_mode_text


class MessageListener:
    """Message Listener interface."""

    def __init__(self, coordinator) -> None:
        """Initialize listener."""
        self.coordinator = coordinator

    def on_message(self, state: InverterState) -> None:
        """Handle incoming messages."""
        import contextlib
        with contextlib.suppress(AttributeError):
            self.coordinator.set_update_interval(fast=True)
        self.coordinator.async_set_updated_data(state)


class EsySunhomeBattery:
    """ESY Sunhome Battery Controller using v2.0.0 binary MQTT protocol."""

    def __init__(
        self,
        username: str,
        password: str,
        device_id: str,
        user_id: Optional[str] = None,
    ) -> None:
        """Initialize the battery controller.

        Args:
            username: API username
            password: API password
            device_id: Device ID for MQTT topics
            user_id: User ID for MQTT commands (optional)
        """
        self.username = username
        self.password = password
        self.device_id = device_id
        self.user_id = user_id or ""

        # MQTT topics (v2.0.0 binary protocol)
        self._topics = get_mqtt_topics(device_id)
        self.topic_up = self._topics["up"]
        self.topic_down = self._topics["down"]
        self.topic_alarm = self._topics["alarm"]

        # Protocol handlers
        self._parser = ESYTelemetryParser()
        self._command_builder: Optional[ESYCommandBuilder] = None
        if user_id:
            self._command_builder = ESYCommandBuilder(user_id)

        # MQTT state
        self._client: Optional[aiomqtt.Client] = None
        self._connected = False
        self._listener_task: Optional[asyncio.Task] = None
        self._last_state: Optional[InverterState] = None

        # API client (for fallback operations like mode setting via REST)
        self.api = None

        _LOGGER.info(
            "Initialized battery controller for device %s with topics: UP=%s, DOWN=%s",
            device_id,
            self.topic_up,
            self.topic_down,
        )

    def connect(self, listener: MessageListener) -> None:
        """Connect to MQTT server and subscribe for updates."""
        self._listener_task = asyncio.create_task(self._listen(listener))

    async def _listen(self, listener: MessageListener) -> None:
        """Main MQTT listening loop."""
        self._connected = True

        while self._connected:
            try:
                async with aiomqtt.Client(
                    hostname=ESY_MQTT_BROKER_URL,
                    port=ESY_MQTT_BROKER_PORT,
                    username=self.username,
                    password=self.password,
                ) as self._client:
                    _LOGGER.info(
                        "Connected to MQTT broker (authenticated), subscribing to %s",
                        self.topic_up,
                    )

                    # Subscribe to telemetry and alarm topics
                    await self._client.subscribe(self.topic_up)
                    await self._client.subscribe(self.topic_alarm)

                    _LOGGER.info("Subscribed to MQTT topics")

                    # Process messages
                    async for message in self._client.messages:
                        try:
                            self._process_message(message, listener)
                        except Exception as e:
                            _LOGGER.error("Error processing message: %s", e)

            except aiomqtt.MqttError as mqtt_err:
                # Check for authentication errors (code 135 = Not authorized)
                error_str = str(mqtt_err)
                if "135" in error_str or "Not authorized" in error_str:
                    _LOGGER.error(
                        "MQTT authentication failed (code 135). Check credentials. Error: %s",
                        mqtt_err,
                    )
                else:
                    _LOGGER.warning(
                        "MQTT connection error, will retry in 5s: %s",
                        mqtt_err,
                    )
                self._client = None
            except asyncio.CancelledError:
                _LOGGER.debug("MQTT listener cancelled")
                raise
            except Exception as e:
                _LOGGER.error("Exception in MQTT loop: %s", e)
            finally:
                if self._connected:
                    await asyncio.sleep(5)

    def _process_message(self, message: aiomqtt.Message, listener: MessageListener) -> None:
        """Process incoming MQTT message."""
        topic = str(message.topic)
        payload = message.payload

        if topic == self.topic_up:
            # Telemetry message (binary)
            self._handle_telemetry(payload, listener)
        elif topic == self.topic_alarm:
            # Alarm message
            self._handle_alarm(payload)
        else:
            _LOGGER.debug("Unknown topic: %s", topic)

    def _handle_telemetry(self, payload: bytes, listener: MessageListener) -> None:
        """Handle incoming telemetry message."""
        if not payload:
            _LOGGER.debug("Empty telemetry payload")
            return

        _LOGGER.debug("Received telemetry: %d bytes", len(payload))

        # Parse binary protocol
        telemetry = self._parser.parse_message(payload)

        if telemetry is None:
            _LOGGER.warning("Failed to parse telemetry message")
            return

        # Create state object
        state = InverterState(telemetry)
        self._last_state = state

        _LOGGER.debug(
            "Parsed telemetry: SOC=%d%%, PV=%dW, Battery=%dW, Grid=%dW, Load=%dW",
            state.battery_soc,
            state.pv_power,
            state.battery_power,
            state.grid_power,
            state.load_power,
        )

        # Notify listener
        listener.on_message(state)

    def _handle_alarm(self, payload: bytes) -> None:
        """Handle incoming alarm message."""
        _LOGGER.warning("Alarm received: %s", payload.hex() if payload else "empty")

    async def disconnect(self) -> None:
        """Disconnect from MQTT server."""
        if self._listener_task is None:
            return

        self._connected = False
        self._listener_task.cancel()

        try:
            await self._listener_task
        except asyncio.CancelledError:
            _LOGGER.debug("Listener task cancelled")

        self._listener_task = None
        self._client = None

    async def send_command(
        self,
        register_address: int,
        value: int,
    ) -> bool:
        """Send a command to the inverter via MQTT.

        Args:
            register_address: The register address to write to
            value: The value to write

        Returns:
            True if command was sent successfully
        """
        if not self._command_builder:
            _LOGGER.error("Cannot send command: no user_id configured")
            return False

        if not self._client:
            _LOGGER.error("Cannot send command: not connected to MQTT")
            return False

        try:
            command = self._command_builder.build_write_command(
                register_address,
                value,
            )

            await self._client.publish(self.topic_down, command)
            _LOGGER.info(
                "Sent command to register %d with value %d",
                register_address,
                value,
            )
            return True
        except Exception as e:
            _LOGGER.error("Failed to send command: %s", e)
            return False

    async def request_update(self) -> None:
        """Request an update from the inverter.

        For the v2.0.0 protocol, the inverter pushes data automatically.
        This method is kept for backwards compatibility but may use the
        REST API fallback if configured.
        """
        if self.api:
            try:
                await self.api.request_update()
            except Exception as e:
                _LOGGER.debug("REST API update request failed: %s", e)

    async def set_value(self, value_name: str, value: int) -> None:
        """Set a value on the inverter.

        Args:
            value_name: The name of the value to set (e.g., "code" for mode)
            value: The value to set
        """
        from .const import ATTR_SCHEDULE_MODE

        if value_name == ATTR_SCHEDULE_MODE:
            # Mode setting - use REST API for now as MQTT command
            # register addresses need to be mapped
            if self.api:
                await self.api.set_mode(value)
            else:
                _LOGGER.warning("Cannot set mode: API not initialized")


# Backwards compatibility alias
BatteryState = InverterState

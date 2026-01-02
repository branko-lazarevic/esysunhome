"""
ESY SunHome MQTT Protocol Parser - Dynamic Version

Parses binary telemetry from MQTT using dynamically loaded register definitions
from the ESY API, ensuring correct mappings for all device models.
"""

import struct
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
from enum import IntEnum

from .protocol_api import ProtocolDefinition, RegisterDefinition, get_protocol_api
from .const import (
    DATA_TYPE_SIGNED,
    FC_READ_INPUT,
    FC_READ_HOLDING,
)

_LOGGER = logging.getLogger(__name__)

HEADER_SIZE = 24


class FunctionCode(IntEnum):
    """MQTT message function codes."""
    READ = 0x03
    WRITE_SINGLE = 0x06
    WRITE_MULTIPLE = 0x10
    RESPONSE = 0x20
    ALARM = 0x83


@dataclass
class MsgHeader:
    """MQTT message header structure."""
    config_id: int
    msg_id: int
    user_id: bytes
    fun_code: int
    source_id: int
    page_index: int
    data_length: int

    @classmethod
    def from_bytes(cls, data: bytes) -> Optional["MsgHeader"]:
        """Parse header from bytes."""
        if len(data) < HEADER_SIZE:
            return None
        try:
            config_id = struct.unpack(">I", data[0:4])[0]
            msg_id = struct.unpack(">I", data[4:8])[0]
            user_id = data[8:16]
            fun_code = data[16]
            source_id = data[17]
            page_index = struct.unpack(">H", data[18:20])[0]
            data_length = struct.unpack(">I", data[20:24])[0]
            return cls(config_id, msg_id, user_id, fun_code, source_id, page_index, data_length)
        except Exception as e:
            _LOGGER.error("Failed to parse header: %s", e)
            return None

    def to_bytes(self) -> bytes:
        """Serialize header to bytes."""
        return (
            struct.pack(">I", self.config_id)
            + struct.pack(">I", self.msg_id)
            + self.user_id
            + bytes([self.fun_code, self.source_id])
            + struct.pack(">H", self.page_index)
            + struct.pack(">I", self.data_length)
        )


@dataclass
class ParamSegment:
    """Represents a segment of parameters in the payload."""
    segment_id: int
    segment_type: int
    segment_address: int
    params_num: int
    values: bytes = field(default_factory=bytes)


class PayloadParser:
    """Parser for MQTT payload segments."""

    def parse(self, payload: bytes) -> List[ParamSegment]:
        """Parse payload into segments."""
        if len(payload) < 2:
            return []

        # First 2 bytes are segment count
        segment_count = (payload[0] << 8) | payload[1]
        _LOGGER.debug("PayloadParser: segment_count = %d, total data = %d bytes", 
                     segment_count, len(payload))

        segments = []
        pos = 2

        for i in range(segment_count):
            if pos + 8 > len(payload):
                _LOGGER.warning("Not enough data for segment %d header", i)
                break

            # Each segment header is 8 bytes (4 x 16-bit values)
            seg_id = (payload[pos] << 8) | payload[pos + 1]
            seg_type = (payload[pos + 2] << 8) | payload[pos + 3]  # Function code: 3=Holding, 4=Input
            seg_addr = (payload[pos + 4] << 8) | payload[pos + 5]
            params_num = (payload[pos + 6] << 8) | payload[pos + 7]
            pos += 8

            # Values length is params_num * 2 (each param is 16 bits)
            values_len = params_num * 2
            if pos + values_len > len(payload):
                _LOGGER.warning("Segment %d: not enough data (need %d, have %d)",
                               i, values_len, len(payload) - pos)
                break

            seg_values = payload[pos:pos + values_len]
            pos += values_len

            segment = ParamSegment(
                segment_id=seg_id,
                segment_type=seg_type,
                segment_address=seg_addr,
                params_num=params_num,
                values=seg_values
            )
            segments.append(segment)

            fc_name = "Holding" if seg_type == 3 else "Input" if seg_type == 4 else f"FC{seg_type}"
            _LOGGER.debug("Segment[%d]: id=%d, type=%d (%s), addr=%d (0x%04X), params=%d",
                         i, seg_id, seg_type, fc_name, seg_addr, seg_addr, params_num)

        return segments


class DynamicTelemetryParser:
    """Parser that uses dynamically loaded protocol definitions."""

    def __init__(self, protocol: Optional[ProtocolDefinition] = None):
        """Initialize with optional protocol definition."""
        self.protocol = protocol
        self.payload_parser = PayloadParser()
        
        # Key mappings for legacy compatibility
        self._legacy_key_map = {
            "battTotalSoc": "batterySoc",
            "ct1Power": "gridPower",
            "loadRealTimePower": "loadPower",
            "gridFreq": "gridFrequency",
            "gridVolt": "gridVoltage",
            "invTemperature": "inverterTemp",
            "pv1voltage": "pv1Voltage",
            "pv1current": "pv1Current",
            "pv2voltage": "pv2Voltage",
            "pv2current": "pv2Current",
            "dailyEnergyGeneration": "dailyPowerGeneration",
            "totalEnergyGeneration": "totalPowerGeneration",
            "dailyPowerConsumption": "dailyConsumption",
            "dailyBattChargeEnergy": "dailyBattCharge",
            "dailyBattDischargeEnergy": "dailyBattDischarge",
            "dailyGridConnectionPower": "dailyGridExport",
            "energyFlowPvTotalPower": "energyFlowPv",
            "energyFlowBattPower": "energyFlowBatt",
            "energyFlowGridPower": "energyFlowGrid",
            "energyFlowLoadTotalPower": "energyFlowLoad",
        }

    def set_protocol(self, protocol: ProtocolDefinition):
        """Set the protocol definition to use."""
        self.protocol = protocol
        _LOGGER.info("Protocol definition updated: %d input regs, %d holding regs",
                     len(protocol.input_registers), len(protocol.holding_registers))

    def parse_message(self, data: bytes) -> Optional[Dict[str, Any]]:
        """Parse binary telemetry message into dict."""
        if not data or len(data) < HEADER_SIZE:
            _LOGGER.warning("Message too short: %d bytes", len(data) if data else 0)
            return None

        # Parse header
        header = MsgHeader.from_bytes(data)
        if not header:
            _LOGGER.error("Failed to parse header")
            return None

        _LOGGER.debug("Header: configId=%d, funCode=%d, pageIndex=%d, dataLen=%d",
                     header.config_id, header.fun_code, header.page_index, header.data_length)

        # Extract and parse payload
        payload = data[HEADER_SIZE:HEADER_SIZE + header.data_length]
        segments = self.payload_parser.parse(payload)
        
        _LOGGER.debug("Parsed %d segments", len(segments))

        # Build telemetry data
        result = self._build_telemetry_data(segments, header)
        
        # Map to legacy entity names and compute derived values
        result = self._compute_derived_values(result)

        return result

    def _build_telemetry_data(self, segments: List[ParamSegment], header: MsgHeader) -> Dict[str, Any]:
        """Build telemetry dict from segments using dynamic protocol."""
        all_values: Dict[str, Any] = {}
        
        all_values["_configId"] = header.config_id
        all_values["_pageIndex"] = header.page_index
        all_values["_funCode"] = header.fun_code
        all_values["_segmentCount"] = len(segments)

        for segment in segments:
            base_addr = segment.segment_address
            values_bytes = segment.values
            
            # Use segment_type as the function code (3=Holding, 4=Input)
            fc = segment.segment_type

            for i in range(segment.params_num):
                abs_addr = base_addr + i
                offset = i * 2

                if offset + 2 > len(values_bytes):
                    break

                raw_unsigned = (values_bytes[offset] << 8) | values_bytes[offset + 1]
                
                # Try to find register in protocol
                reg = None
                if self.protocol:
                    reg = self.protocol.get_register(abs_addr, fc)
                
                if reg:
                    # Apply data type
                    if reg.data_type == DATA_TYPE_SIGNED and raw_unsigned > 32767:
                        raw_value = raw_unsigned - 65536
                    else:
                        raw_value = raw_unsigned
                    
                    # Apply coefficient
                    if reg.coefficient != 1:
                        value = round(raw_value * reg.coefficient, 3)
                    else:
                        value = raw_value
                    
                    # Store with original key
                    all_values[reg.data_key] = value
                    
                    # Also store with legacy key if applicable
                    if reg.data_key in self._legacy_key_map:
                        all_values[self._legacy_key_map[reg.data_key]] = value
                    
                    _LOGGER.debug("%s = %s (raw=%d, coeff=%s, addr=%d)",
                                 reg.data_key, value, raw_value, reg.coefficient, abs_addr)
                else:
                    # Store unknown registers for debugging
                    if raw_unsigned != 0:
                        all_values[f"_unknown_fc{fc}_addr{abs_addr}"] = raw_unsigned

        return all_values

    def _compute_derived_values(self, values: Dict[str, Any]) -> Dict[str, Any]:
        """Compute derived values for compatibility."""
        result = dict(values)
        
        # === PV POWER ===
        # For DC-coupled: pv1Power + pv2Power
        # For AC-coupled: energyFlowPvTotalPower (pv1/pv2 will be 0)
        pv1 = values.get("pv1Power", 0) or 0
        pv2 = values.get("pv2Power", 0) or 0
        dc_pv_power = pv1 + pv2
        
        # energyFlowPvTotalPower is the app's display value - use it for AC-coupled
        energy_flow_pv = values.get("energyFlowPvTotalPower", 0) or 0
        
        # Use DC-coupled value if available, otherwise use energy flow (AC-coupled)
        if dc_pv_power > 0:
            result["pvPower"] = dc_pv_power
        else:
            result["pvPower"] = int(energy_flow_pv)
        
        result["pv1Power"] = pv1
        result["pv2Power"] = pv2
        result["pvLine"] = 1 if result["pvPower"] > 10 else 0
        
        _LOGGER.debug("PV: pv1=%d, pv2=%d, energyFlow=%d -> pvPower=%d",
                     pv1, pv2, int(energy_flow_pv), result["pvPower"])
        
        # === GRID POWER ===
        # Different inverter setups use different sensors for grid power:
        # - Some use ct1Power (with sign)
        # - Some use ct2Power 
        # - gridActivePower is often accurate but sometimes has scaling issues
        # - energyFlowGridPower matches the app display
        # Negative values = importing FROM grid
        
        ct1_power = values.get("ct1Power") or 0
        ct2_power = values.get("ct2Power") or 0
        grid_active_power = values.get("gridActivePower") or 0
        energy_flow_grid = values.get("energyFlowGridPower", 0) or values.get("energyFlowGrid", 0) or 0
        
        # Choose the best source based on which has meaningful data
        # Prefer ct1Power if it has significant magnitude, otherwise fall back
        if abs(ct1_power) > 10:
            grid_power = ct1_power
            grid_source = "ct1"
        elif abs(grid_active_power) > 10:
            grid_power = grid_active_power
            grid_source = "active"
        elif abs(energy_flow_grid) > 10:
            grid_power = int(energy_flow_grid)
            grid_source = "flow"
        elif abs(ct2_power) > 10:
            # ct2Power may not have sign - use gridActivePower sign if available
            if grid_active_power < 0:
                grid_power = -abs(ct2_power)
            else:
                grid_power = ct2_power
            grid_source = "ct2"
        else:
            grid_power = ct1_power or grid_active_power or int(energy_flow_grid)
            grid_source = "fallback"
        
        # Negative = importing, Positive = exporting
        # For Home Assistant: gridPower positive = import, negative = export
        # So we need to FLIP the sign from ESY convention
        result["gridPower"] = -grid_power  # Flip sign for HA convention
        
        if grid_power < 0:
            # ESY negative = importing from grid
            result["gridImport"] = abs(grid_power)
            result["gridExport"] = 0
        elif grid_power > 0:
            # ESY positive = exporting to grid
            result["gridImport"] = 0
            result["gridExport"] = grid_power
        else:
            result["gridImport"] = 0
            result["gridExport"] = 0
        
        result["gridLine"] = 1 if grid_power != 0 else 0
        
        _LOGGER.debug("Grid: ct1=%d, ct2=%d, active=%d, flow=%d -> power=%d [%s] (import=%d, export=%d)",
                     ct1_power, ct2_power, grid_active_power, int(energy_flow_grid),
                     grid_power, grid_source, result["gridImport"], result["gridExport"])
        
        # === BATTERY POWER ===
        # Standard convention: Positive = Charging, Negative = Discharging
        
        raw_batt_power = (
            values.get("batteryPower") or
            values.get("energyFlowBatt", 0) or 0
        )
        
        batt_power = raw_batt_power
        
        if batt_power > 0:
            is_charging = True
            is_discharging = False
        elif batt_power < 0:
            is_charging = False
            is_discharging = True
        else:
            is_charging = False
            is_discharging = False
        
        result["batteryPower"] = batt_power
        
        # Directional battery power for HA sensors
        if is_charging:
            result["batteryImport"] = batt_power  # Charging = import
            result["batteryExport"] = 0
            result["batteryStatusText"] = "Charging"
            result["batteryLine"] = 2
        elif is_discharging:
            result["batteryImport"] = 0
            result["batteryExport"] = abs(batt_power)  # Discharging = export
            result["batteryStatusText"] = "Discharging"
            result["batteryLine"] = 1
        else:
            result["batteryImport"] = 0
            result["batteryExport"] = 0
            result["batteryStatusText"] = "Idle"
            result["batteryLine"] = 0
        
        _LOGGER.debug("Battery: power=%d (%s)", batt_power, result["batteryStatusText"])
        
        # === LOAD POWER ===
        load_power = (
            values.get("loadRealTimePower") or
            values.get("loadActivePower") or
            values.get("loadPower") or
            values.get("energyFlowLoad", 0) or 0
        )
        result["loadPower"] = load_power
        result["loadLine"] = 1 if load_power > 10 else 0
        
        # === BATTERY SOC ===
        # Priority: battTotalSoc (addr 32) > batterySoc (addr 290)
        soc = values.get("battTotalSoc") or values.get("batterySoc") or 0
        if 0 <= soc <= 100:
            result["batterySoc"] = soc
        else:
            result["batterySoc"] = 0
        
        # === BATTERY SOH ===
        result["batterySoh"] = values.get("batterySoh", 0) or 0
        
        # === TEMPERATURES ===
        result["inverterTemp"] = values.get("invTemperature") or values.get("inverterTemp") or 0
        result["dcdcTemperature"] = values.get("dcdcTemperature") or 0
        
        # === ENERGY STATISTICS ===
        result["dailyPowerGeneration"] = values.get("dailyEnergyGeneration") or values.get("dailyPowerGeneration") or 0
        result["totalPowerGeneration"] = values.get("totalEnergyGeneration") or values.get("totalPowerGeneration") or 0
        result["dailyConsumption"] = values.get("dailyPowerConsumption") or values.get("dailyConsumption") or 0
        result["dailyGridExport"] = values.get("dailyGridConnectionPower") or values.get("dailyGridExport") or 0
        result["dailyBattCharge"] = values.get("dailyBattChargeEnergy") or values.get("dailyBattCharge") or 0
        result["dailyBattDischarge"] = values.get("dailyBattDischargeEnergy") or values.get("dailyBattDischarge") or 0
        
        # === VOLTAGE & FREQUENCY ===
        result["gridVoltage"] = values.get("gridVolt") or values.get("gridVoltage") or 0
        result["gridFrequency"] = values.get("gridFreq") or values.get("gridFrequency") or 0
        result["batteryVoltage"] = values.get("batteryVoltage") or 0
        result["batteryCurrent"] = values.get("batteryCurrent") or 0
        
        # === SYSTEM MODE ===
        # Mode codes from APK analysis:
        # 1 = Regular Mode
        # 2 = Emergency Mode  
        # 3 = Electricity Selling Mode
        # 4 = AI Mode
        # 5 = Battery Energy Management
        # 6 = Battery Priority Mode
        # 7 = AC Charging Off Emergency Backup Mode
        # 8 = PV Mode
        # 9 = Forced Off Grid Mode
        #
        # Register 5 (systemRunMode) = The ACTUAL mode the system is running in
        # Register 6 (systemRunStatus) = Run STATUS indicator (NOT the mode!)
        #   Status values might indicate: 0=Standby, 5=Running, etc.
        #
        MODE_NAMES = {
            1: "Regular Mode",
            2: "Emergency Mode",
            3: "Electricity Sell Mode",
            4: "AI Mode",
            5: "Battery Energy Management",
            6: "Battery Priority Mode",
            7: "AC Charging Off Emergency",
            8: "PV Mode",
            9: "Forced Off Grid Mode",
        }
        
        # systemRunMode (register 5) is the ACTUAL mode
        running_mode = values.get("systemRunMode") or 1
        
        # systemRunStatus (register 6) is NOT the mode - it's a status indicator
        run_status = values.get("systemRunStatus") or 0
        
        # The display mode should be the running mode
        display_mode = running_mode
        
        result["systemRunMode"] = running_mode  # The actual mode
        result["systemRunStatus"] = run_status  # Run status (not mode)
        result["patternMode"] = running_mode    # For backwards compatibility
        result["code"] = MODE_NAMES.get(display_mode, f"Unknown Mode ({display_mode})")
        result["_modeCode"] = display_mode
        result["_runningModeCode"] = running_mode
        
        _LOGGER.debug("Mode: systemRunMode=%d, systemRunStatus=%d, display='%s'", 
                     running_mode, run_status, result["code"])
        
        # === RATED POWER ===
        rated = values.get("ratedPower") or 0
        # Handle coefficient if needed
        if 10 < rated < 200:  # Likely in hundreds of watts
            result["ratedPower"] = rated * 100
        else:
            result["ratedPower"] = rated
        
        # === METER/CT POWER ===
        result["ct1Power"] = values.get("ct1Power") or 0
        result["ct2Power"] = values.get("ct2Power") or 0
        result["meterPower"] = values.get("meterPower") or 0
        
        # === ENERGY FLOW (app display) ===
        result["energyFlowPv"] = values.get("energyFlowPvTotalPower") or values.get("energyFlowPv") or 0
        result["energyFlowBatt"] = values.get("energyFlowBattPower") or values.get("energyFlowBatt") or 0
        result["energyFlowGrid"] = values.get("energyFlowGridPower") or values.get("energyFlowGrid") or 0
        result["energyFlowLoad"] = values.get("energyFlowLoadTotalPower") or values.get("energyFlowLoad") or 0
        
        _LOGGER.debug("=== PARSED VALUES ===")
        _LOGGER.debug("PV: %dW (pv1=%d, pv2=%d)", result["pvPower"], pv1, pv2)
        _LOGGER.debug("Grid: %dW (import=%d, export=%d)", result["gridPower"], result["gridImport"], result["gridExport"])
        _LOGGER.debug("Battery: %dW (SOC=%d%%, status=%s)", result["batteryPower"], result["batterySoc"], result["batteryStatusText"])
        _LOGGER.debug("Load: %dW", result["loadPower"])
        _LOGGER.debug("Daily Gen: %.2f kWh", result["dailyPowerGeneration"])
        _LOGGER.debug("Mode: %s (code=%d)", result["code"], result.get("_modeCode", 0))
        
        return result


class ESYCommandBuilder:
    """Builder for commands to send to inverter."""

    @staticmethod
    def build_write_command(
        register_address: int,
        value: int,
        user_id: bytes = None,
        msg_id: int = 0,
    ) -> bytes:
        """Build a write command for a single register.
        
        Based on MQTT traffic analysis, write commands use:
        - fun_code = 0x00
        - source_id = 0x10
        - page_index = 0x0800
        
        Payload format:
        - num_operations (2 bytes)
        - address (2 bytes)
        - count (2 bytes)
        - value (2 bytes per count)
        
        Args:
            register_address: Register address to write (e.g., 57 for mode)
            value: Value to write
            user_id: 8-byte user ID (default: all 0xFF)
            msg_id: Message ID
            
        Returns:
            Binary command to publish to DOWN topic
        """
        if user_id is None:
            user_id = bytes([0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFC, 0x17])
        
        # Payload: num_ops(2) + addr(2) + count(2) + value(2)
        payload = struct.pack(">HHHH", 
            1,                  # 1 operation
            register_address,   # address
            1,                  # 1 value
            value               # the value
        )
        
        header = MsgHeader(
            config_id=0,
            msg_id=msg_id,
            user_id=user_id,
            fun_code=0x00,      # Write command
            source_id=0x10,     # From app
            page_index=0x0800,  # Write page
            data_length=len(payload)
        )

        return header.to_bytes() + payload

    @staticmethod
    def build_multi_write_command(
        writes: List[tuple],  # List of (address, values) tuples
        user_id: bytes = None,
        msg_id: int = 0,
    ) -> bytes:
        """Build a write command for multiple registers.
        
        Args:
            writes: List of (address, [values]) tuples
            user_id: 8-byte user ID (default: all 0xFF)
            msg_id: Message ID
            
        Returns:
            Binary command to publish to DOWN topic
        """
        if user_id is None:
            user_id = bytes([0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFC, 0x17])
        
        # Build payload
        payload = struct.pack(">H", len(writes))  # num_operations
        
        for addr, values in writes:
            if isinstance(values, int):
                values = [values]
            payload += struct.pack(">HH", addr, len(values))  # addr, count
            for val in values:
                payload += struct.pack(">H", val)  # each value
        
        header = MsgHeader(
            config_id=0,
            msg_id=msg_id,
            user_id=user_id,
            fun_code=0x00,
            source_id=0x10,
            page_index=0x0800,
            data_length=len(payload)
        )

        return header.to_bytes() + payload

    @staticmethod
    def build_poll_request(
        segment_ids: List[int],
        msg_id: int = 0,
        user_id: bytes = None
    ) -> bytes:
        """Build a poll request to request specific segments from inverter.
        
        This is the DOWN command the app sends to request data updates.
        The inverter responds on the UP topic with only the requested segments.
        
        Args:
            segment_ids: List of segment IDs to request (e.g., [0, 1, 3, 6])
            msg_id: Message ID (incrementing counter)
            user_id: 8-byte user ID (default: all 0xFF)
            
        Returns:
            Binary command to publish to DOWN topic
        """
        if user_id is None:
            user_id = bytes([0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFC, 0x17])
        
        # Payload: segment count (2 bytes) + segment IDs (2 bytes each)
        payload = bytearray()
        payload.extend(struct.pack(">H", len(segment_ids)))  # Count
        for seg_id in segment_ids:
            payload.extend(struct.pack(">H", seg_id))
        
        # Header for poll request
        # fun_code = 0x20 (response/poll), source_id = 0x10, page_index = 0x0300
        header = MsgHeader(
            config_id=0,
            msg_id=msg_id,
            user_id=user_id,
            fun_code=0x20,
            source_id=0x10,
            page_index=0x0300,
            data_length=len(payload)
        )
        
        return header.to_bytes() + bytes(payload)


# Convenience function
def create_parser(protocol: Optional[ProtocolDefinition] = None) -> DynamicTelemetryParser:
    """Create a new telemetry parser."""
    return DynamicTelemetryParser(protocol)


# Compatibility aliases for legacy code
ESYTelemetryParser = DynamicTelemetryParser


def parse_telemetry(data: bytes) -> Optional[Dict[str, Any]]:
    """Parse telemetry data - compatibility function."""
    parser = DynamicTelemetryParser()
    return parser.parse_message(data)

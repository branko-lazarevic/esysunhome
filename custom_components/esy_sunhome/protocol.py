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
        pv1 = values.get("pv1Power", 0) or 0
        pv2 = values.get("pv2Power", 0) or 0
        result["pvPower"] = pv1 + pv2
        result["pv1Power"] = pv1
        result["pv2Power"] = pv2
        result["pvLine"] = 1 if result["pvPower"] > 10 else 0
        
        # === GRID POWER ===
        # Priority: ct1Power > gridActivePower > energyFlowGrid
        grid_power = (
            values.get("ct1Power") or
            values.get("gridActivePower") or
            values.get("gridPower") or
            (values.get("energyFlowGrid", 0) or 0)
        )
        result["gridPower"] = grid_power or 0
        
        # Directional grid power
        if result["gridPower"] >= 0:
            result["gridImport"] = result["gridPower"]
            result["gridExport"] = 0
        else:
            result["gridImport"] = 0
            result["gridExport"] = abs(result["gridPower"])
        
        result["gridLine"] = 1 if result["gridPower"] != 0 else 0
        
        # === BATTERY POWER ===
        # The battery power value may be:
        # 1. Signed: positive=charging, negative=discharging
        # 2. Unsigned/absolute: direction from batteryLine or batteryStatus
        #
        # batteryLine: 1=discharging, 2=charging
        # batteryStatus: 1=charging, 2=discharging
        
        raw_batt_power = (
            values.get("batteryPower") or
            values.get("energyFlowBatt", 0) or 0
        )
        
        # Get direction indicators
        batt_line = values.get("batteryLine") or values.get("battLine") or 0
        batt_status = values.get("batteryStatus") or values.get("battChgStatus") or 0
        
        # Determine if we need to apply direction from status fields
        # If raw value is already signed (negative), trust it
        if raw_batt_power < 0:
            # Already signed negative = discharging
            batt_power = raw_batt_power
            is_charging = False
            is_discharging = True
        elif raw_batt_power > 0:
            # Positive value - check if we need to flip sign based on status
            # batteryLine: 1=discharging, 2=charging
            # batteryStatus: 1=charging, 2=discharging
            if batt_line == 1 or batt_status == 2:
                # Discharging - make negative
                batt_power = -abs(raw_batt_power)
                is_charging = False
                is_discharging = True
            elif batt_line == 2 or batt_status == 1:
                # Charging - keep positive
                batt_power = abs(raw_batt_power)
                is_charging = True
                is_discharging = False
            else:
                # No direction info - assume positive = charging (convention)
                batt_power = raw_batt_power
                is_charging = True
                is_discharging = False
        else:
            batt_power = 0
            is_charging = False
            is_discharging = False
        
        result["batteryPower"] = batt_power
        
        # Directional battery power for HA sensors
        if is_charging:
            result["batteryImport"] = abs(batt_power)  # Charging
            result["batteryExport"] = 0
            result["batteryStatusText"] = "Charging"
            result["batteryLine"] = 2
        elif is_discharging:
            result["batteryImport"] = 0
            result["batteryExport"] = abs(batt_power)  # Discharging
            result["batteryStatusText"] = "Discharging"
            result["batteryLine"] = 1
        else:
            result["batteryImport"] = 0
            result["batteryExport"] = 0
            result["batteryStatusText"] = "Idle"
            result["batteryLine"] = 0
        
        _LOGGER.debug("Battery: raw=%d, line=%d, status=%d -> power=%d (%s)",
                     raw_batt_power, batt_line, batt_status, batt_power, result["batteryStatusText"])
        
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
        # Mode codes: 1=Regular, 2=Emergency, 3=Sell First, 5=Battery Management
        # 
        # There are TWO mode values:
        # - Input Register 5 (FC4): systemRunMode = what's CURRENTLY running
        # - Holding Register 57 (FC3): systemRunMode = the CONFIGURED pattern/schedule mode
        #
        # When in "Battery Energy Management" (5), the system follows a schedule.
        # Register 5 will show the current mode (e.g., 1) based on the schedule,
        # while register 57 shows the pattern (5 = BEM).
        #
        # The select entity should show the pattern mode (57) if available.
        MODE_NAMES = {
            1: "Regular Mode",
            2: "Emergency Mode",
            3: "Electricity Sell Mode",
            5: "Battery Energy Management",
        }
        
        # Get mode values - check for pattern mode from holding registers
        running_mode = values.get("systemRunMode") or 1  # From input register 5
        pattern_mode = values.get("patternMode") or values.get("workMode") or 0  # From holding register 57
        
        # For the select entity, use pattern mode if available, else running mode
        display_mode = pattern_mode if pattern_mode > 0 else running_mode
        
        result["systemRunMode"] = running_mode  # Current mode (from MQTT input registers)
        result["patternMode"] = pattern_mode    # Pattern mode (from MQTT holding registers, if present)
        result["systemRunStatus"] = values.get("systemRunStatus") or 0
        result["code"] = MODE_NAMES.get(display_mode, f"Unknown Mode ({display_mode})")
        result["_modeCode"] = display_mode
        result["_runningModeCode"] = running_mode
        
        _LOGGER.debug("Mode: running=%d, pattern=%d, display='%s'", 
                     running_mode, pattern_mode, result["code"])
        
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
        config_id: int,
        register_address: int,
        value: int,
        page_index: int = 3,
        source_id: int = 1
    ) -> bytes:
        """Build a write command for a single register."""
        payload = bytearray(4)
        payload[0] = (register_address >> 8) & 0xFF
        payload[1] = register_address & 0xFF
        payload[2] = (value >> 8) & 0xFF
        payload[3] = value & 0xFF

        header = MsgHeader(
            config_id=config_id,
            msg_id=0,
            user_id=bytes(8),
            fun_code=FunctionCode.WRITE_SINGLE,
            source_id=source_id,
            page_index=page_index,
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

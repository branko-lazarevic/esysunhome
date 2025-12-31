"""
ESY SunHome / BenBen Energy Inverter - MQTT Binary Protocol Parser

This module provides parsing logic for the binary MQTT protocol used by ESY HM6 inverters.

MQTT Topics:
- /ESY/PVVC/{device_id}/UP    - Telemetry FROM inverter (subscribe)
- /ESY/PVVC/{device_id}/DOWN  - Commands TO inverter (publish)
- /ESY/PVVC/{device_id}/ALARM - Alarm messages (subscribe)

MQTT Broker:
- tcp://abroadtcp.esysunhome.com:1883
"""

from __future__ import annotations

import struct
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
from enum import IntEnum
from decimal import Decimal

_LOGGER = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

HEADER_SIZE = 24  # 0x18 bytes


class FunctionCode(IntEnum):
    """MQTT message function codes"""
    READ = 0x03
    WRITE_SINGLE = 0x06
    WRITE_MULTIPLE = 0x10
    RESPONSE = 0x83


class DataType(IntEnum):
    """Data type codes for value parsing"""
    DEFAULT = 0
    SIGNED_16 = 1
    UNSIGNED_16 = 2
    SIGNED_32 = 3
    STRING_VAR = 4
    STRING_FIXED = 5
    BYTE_ARRAY = 6
    DATE_TIME = 100


# =============================================================================
# BYTE CONVERSION UTILITIES
# =============================================================================

def bytes_to_uint32_be(data: bytes) -> int:
    """Convert 4 bytes to unsigned 32-bit integer (big-endian)"""
    if len(data) < 4:
        return 0
    b0 = data[0] & 0xFF
    b1 = data[1] & 0xFF
    b2 = data[2] & 0xFF
    b3 = data[3] & 0xFF
    return (b3) | (b2 << 8) | (b1 << 16) | (b0 << 24)


def bytes_to_int32_be(data: bytes) -> int:
    """Convert 4 bytes to signed 32-bit integer (big-endian)"""
    if len(data) < 4:
        return 0
    return struct.unpack('>i', data[:4])[0]


def bytes_to_uint16_be(b0: int, b1: int) -> int:
    """Convert 2 bytes to unsigned 16-bit integer"""
    return ((b0 & 0xFF) << 8) | (b1 & 0xFF)


def bytes_to_int16_be(b0: int, b1: int) -> int:
    """Convert 2 bytes to signed 16-bit integer"""
    value = (b0 << 8) | (b1 & 0xFF)
    if value >= 0x8000:
        value -= 0x10000
    return value


def int32_to_bytes_be(value: int) -> bytes:
    """Convert 32-bit integer to 4 bytes (big-endian)"""
    return struct.pack('>i', value)


def int16_to_bytes_be(value: int) -> bytes:
    """Convert 16-bit integer to 2 bytes (big-endian)"""
    return bytes([(value >> 8) & 0xFF, value & 0xFF])


def user_id_to_bytes(user_id: str) -> bytes:
    """Convert user ID string to 8-byte array"""
    result = bytearray(8)
    if not user_id or not user_id.isdigit():
        return bytes(result)

    try:
        value = int(user_id)
        binary = bin(value)[2:]
        padding = (8 - len(binary) % 8) % 8
        binary = '0' * padding + binary

        byte_count = len(binary) // 8
        for i in range(byte_count):
            start = i * 8
            end = start + 8
            result[7 - (byte_count - 1 - i)] = int(binary[start:end], 2)
    except (ValueError, OverflowError):
        pass

    return bytes(result)


# =============================================================================
# MESSAGE HEADER
# =============================================================================

@dataclass
class MsgHeader:
    """
    MQTT message header structure (24 bytes)

    Offset  Size  Field
    ------  ----  -----
    0       4     configId (uint32 BE)
    4       4     msgId (uint32 BE)
    8       8     userId (8 bytes)
    16      1     funCode (uint8)
    17      1     sourceId (uint8, upper 4 bits used)
    18      1     pageIndex (uint8)
    19      3     reserved
    22      2     dataLength (uint16 BE)
    """
    config_id: int = 0
    msg_id: int = 0
    user_id: bytes = field(default_factory=lambda: bytes(8))
    fun_code: int = 0
    source_id: int = 0
    page_index: int = 0
    data_length: int = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> Optional['MsgHeader']:
        """Parse header from byte array"""
        if data is None or len(data) < HEADER_SIZE:
            return None

        config_id = bytes_to_uint32_be(data[0:4])
        msg_id = bytes_to_uint32_be(data[4:8])
        user_id = data[8:16]
        fun_code = data[16] & 0xFF
        source_id = data[17] & 0xFF
        page_index = data[18] & 0xFF
        data_length = bytes_to_uint16_be(data[22], data[23])

        return cls(
            config_id=config_id,
            msg_id=msg_id,
            user_id=user_id,
            fun_code=fun_code,
            source_id=source_id,
            page_index=page_index,
            data_length=data_length
        )

    def to_bytes(self) -> bytes:
        """Serialize header to byte array"""
        result = bytearray(HEADER_SIZE)

        result[0:4] = int32_to_bytes_be(self.config_id)
        result[4:8] = int32_to_bytes_be(self.msg_id)

        user_bytes = self.user_id if isinstance(self.user_id, bytes) else bytes(8)
        result[8:16] = user_bytes[:8].ljust(8, b'\x00')

        result[16] = self.fun_code & 0xFF
        result[17] = (self.source_id << 4) & 0xFF
        result[18] = self.page_index & 0xFF
        result[19:22] = b'\x00\x00\x00'
        result[22:24] = int16_to_bytes_be(self.data_length)

        return bytes(result)


# =============================================================================
# PARAMETER SEGMENT
# =============================================================================

@dataclass
class ParamSegment:
    """Parameter segment within telemetry payload"""
    segment_id: int = 0
    segment_type: int = 0
    segment_address: int = 0
    params_num: int = 0
    values: bytes = field(default_factory=bytes)

    def get_register_value(self, offset: int, length: int = 2) -> bytes:
        """Get raw bytes for a register at offset"""
        start = offset * 2
        end = start + length
        if end <= len(self.values):
            return self.values[start:end]
        return bytes(length)


@dataclass
class ParamsListBean:
    """Container for all parameter segments"""
    segment_count: int = 0
    segments: List[ParamSegment] = field(default_factory=list)


# =============================================================================
# REGISTER DEFINITIONS
# =============================================================================

REGISTER_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    # Run Information
    "systemRunMode": {"length": 1, "type": "unsigned", "unit": ""},
    "systemRunStatus": {"length": 1, "type": "unsigned", "unit": ""},

    # Basic Information
    "dcdcTemperature": {"length": 1, "type": "signed", "unit": "°C"},
    "busVoltage": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "V"},
    "dailyEnergyGeneration": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "kWh"},
    "totalEnergyGeneration": {"length": 2, "type": "unsigned", "coeff": "0.1", "unit": "kWh"},
    "ratedPower": {"length": 1, "type": "unsigned", "unit": "W"},
    "battCapacity": {"length": 1, "type": "unsigned", "unit": "Ah"},

    # PV Information
    "pv1voltage": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "V"},
    "pv1current": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "A"},
    "pv1Power": {"length": 1, "type": "unsigned", "unit": "W"},
    "pv2voltage": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "V"},
    "pv2current": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "A"},
    "pv2Power": {"length": 1, "type": "unsigned", "unit": "W"},

    # Battery Information
    "batteryStatus": {"length": 1, "type": "unsigned"},
    "batteryVoltage": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "V"},
    "batteryCurrent": {"length": 1, "type": "signed", "coeff": "0.1", "unit": "A"},
    "batteryPower": {"length": 1, "type": "signed", "unit": "W"},
    "battTotalSoc": {"length": 1, "type": "unsigned", "unit": "%"},
    "batterySoc": {"length": 1, "type": "unsigned", "unit": "%"},
    "battNum": {"length": 1, "type": "unsigned"},
    "battEnergy": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "kWh"},
    "battCellVoltMax": {"length": 1, "type": "unsigned", "coeff": "0.001", "unit": "V"},
    "battCellVoltMin": {"length": 1, "type": "unsigned", "coeff": "0.001", "unit": "V"},

    # Grid Information
    "gridStatus": {"length": 1, "type": "unsigned"},
    "gridFreq": {"length": 1, "type": "unsigned", "coeff": "0.01", "unit": "Hz"},
    "gridVolt": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "V"},
    "gridApparentPower": {"length": 1, "type": "signed", "unit": "VA"},
    "gridActivePower": {"length": 1, "type": "signed", "unit": "W"},
    "gridReactivePower": {"length": 1, "type": "signed", "unit": "var"},
    "ct1Curr": {"length": 1, "type": "signed", "coeff": "0.1", "unit": "A"},
    "ct1Power": {"length": 1, "type": "signed", "unit": "W"},
    "ct2Curr": {"length": 1, "type": "signed", "coeff": "0.1", "unit": "A"},
    "ct2Power": {"length": 1, "type": "signed", "unit": "W"},
    "onOffGridMode": {"length": 1, "type": "unsigned"},

    # Inverter Information
    "invTemperature": {"length": 1, "type": "signed", "unit": "°C"},
    "invStatus": {"length": 1, "type": "unsigned"},
    "invOutputFreq": {"length": 1, "type": "unsigned", "coeff": "0.01", "unit": "Hz"},
    "invOutputVolt": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "V"},
    "invOutputCurr": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "A"},
    "invApparentPower": {"length": 1, "type": "signed", "unit": "VA"},
    "invActivePower": {"length": 1, "type": "signed", "unit": "W"},
    "invReactivePower": {"length": 1, "type": "signed", "unit": "var"},
    "outputRatedPower": {"length": 1, "type": "unsigned", "unit": "W"},

    # Energy Flow
    "energyFlowPvTotalPower": {"length": 1, "type": "signed", "unit": "W"},
    "energyFlowBattPower": {"length": 1, "type": "signed", "unit": "W"},
    "energyFlowGridPower": {"length": 1, "type": "signed", "unit": "W"},
    "energyFlowLoadTotalPower": {"length": 1, "type": "signed", "unit": "W"},
    "totalPowerOfBatteryInFlow": {"length": 1, "type": "signed", "unit": "W"},
    "totalPowerOfGridInFlow": {"length": 1, "type": "signed", "unit": "W"},

    # Load Information
    "loadVolt": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "V"},
    "loadCurr": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "A"},
    "loadActivePower": {"length": 1, "type": "signed", "unit": "W"},
    "loadRealTimePower": {"length": 1, "type": "signed", "unit": "W"},
    "loadPowerPercentage": {"length": 1, "type": "unsigned", "unit": "%"},

    # Energy Statistics
    "dailyPowerConsumption": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "kWh"},
    "totalEconsumption": {"length": 2, "type": "unsigned", "coeff": "0.1", "unit": "kWh"},
    "dailyGridConnectionPower": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "kWh"},
    "totalOnGridElecGenerated": {"length": 2, "type": "unsigned", "coeff": "0.1", "unit": "kWh"},
    "dailyOnGridElecConsumption": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "kWh"},
    "totalOnGridElecConsumption": {"length": 2, "type": "unsigned", "coeff": "0.1", "unit": "kWh"},
    "dailyBattChargeEnergy": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "kWh"},
    "totalBattChargeEnergy": {"length": 2, "type": "unsigned", "coeff": "0.1", "unit": "kWh"},
    "dailyBattDischargeEnergy": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "kWh"},
    "totalBattDischargeEnergy": {"length": 2, "type": "unsigned", "coeff": "0.1", "unit": "kWh"},
    "dailySelfSufficientElec": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "kWh"},
    "totalSelfSufficientElec": {"length": 2, "type": "unsigned", "coeff": "0.1", "unit": "kWh"},
    "dailySelfUseElec": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "kWh"},
    "totalSelfUseElec": {"length": 2, "type": "unsigned", "coeff": "0.1", "unit": "kWh"},
    "dailySelfSufficientElecPercentage": {"length": 1, "type": "unsigned", "unit": "%"},
    "dailySelfUseElecPercentage": {"length": 1, "type": "unsigned", "unit": "%"},

    # Settings
    "antiBackflowPowerPercentage": {"length": 1, "type": "unsigned", "unit": "%"},
    "batteryChargingCurrent": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "A"},
    "batteryDischargeCurrent": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "A"},
    "onGridSocLimit": {"length": 1, "type": "unsigned", "unit": "%"},
    "offGridSocLimit": {"length": 1, "type": "unsigned", "unit": "%"},

    # Temperature
    "pvTemperature": {"length": 1, "type": "signed", "unit": "°C"},
    "internalTemperature": {"length": 1, "type": "signed", "unit": "°C"},
    "ambientTemp": {"length": 1, "type": "signed", "unit": "°C"},
    "heatingState": {"length": 1, "type": "unsigned"},

    # BMS Information
    "bmsOnlineNumber": {"length": 1, "type": "unsigned"},
    "bmsCommStatus": {"length": 1, "type": "unsigned"},
    "soc": {"length": 1, "type": "unsigned", "unit": "%"},
    "soh": {"length": 1, "type": "unsigned", "unit": "%"},
    "highestTemperature": {"length": 1, "type": "signed", "unit": "°C"},
    "lowestTemperature": {"length": 1, "type": "signed", "unit": "°C"},
    "maxCellVolt": {"length": 1, "type": "unsigned", "coeff": "0.001", "unit": "V"},
    "minCellVolt": {"length": 1, "type": "unsigned", "coeff": "0.001", "unit": "V"},
}

# Energy flow keys for display
ENERGY_FLOW_KEYS_SINGLE_PHASE = [
    "energyFlowChartLineSegmentMarkerApp", "battNum", "onOffGridMode",
    "antiBackflowPowerPercentage", "systemRunMode", "batteryStatus",
    "battTotalSoc", "ct2Power", "pv1Power", "pv2Power",
    "energyFlowChartLineNumber1to8", "energyFlowChartLineNumber9to16",
    "energyFlowChartLineNumber1to16", "ct1Power", "loadRealTimePower",
    "batteryPower", "status", "systemRunStatus", "ratedPower",
    "dailyEnergyGeneration", "energyFlowPvTotalPower", "energyFlowBattPower",
    "energyFlowGridPower", "energyFlowLoadTotalPower"
]


# =============================================================================
# TELEMETRY DATA CONTAINER
# =============================================================================

@dataclass
class TelemetryData:
    """Parsed telemetry data from inverter"""
    # Power values
    pv_power: int = 0
    pv1_power: int = 0
    pv2_power: int = 0
    battery_power: int = 0
    ct1_power: int = 0
    ct2_power: int = 0
    load_power: int = 0
    grid_power: int = 0

    # Energy flow values
    energy_flow_pv_total_power: int = 0
    energy_flow_batt_power: int = 0
    energy_flow_grid_power: int = 0
    energy_flow_load_total_power: int = 0

    # Status values
    on_off_grid_mode: int = 0
    system_run_mode: int = 0
    system_run_status: int = 0
    battery_status: int = 0
    grid_status: int = 0
    inv_status: int = 0

    # Battery
    battery_soc: int = 0
    battery_voltage: float = 0.0
    battery_current: float = 0.0
    batt_num: int = 0

    # PV details
    pv1_voltage: float = 0.0
    pv1_current: float = 0.0
    pv2_voltage: float = 0.0
    pv2_current: float = 0.0

    # Grid details
    grid_voltage: float = 0.0
    grid_frequency: float = 0.0

    # Inverter details
    inv_temperature: int = 0
    inv_output_voltage: float = 0.0
    inv_output_frequency: float = 0.0

    # Energy statistics
    daily_energy_generation: float = 0.0
    total_energy_generation: float = 0.0
    daily_power_consumption: float = 0.0
    total_power_consumption: float = 0.0
    daily_batt_charge_energy: float = 0.0
    daily_batt_discharge_energy: float = 0.0
    daily_grid_import: float = 0.0
    daily_grid_export: float = 0.0

    # Other
    rated_power: int = 0
    anti_backflow_percentage: int = 0
    heating_state: int = 0

    # Raw values dict for debugging
    raw_values: Dict[str, Any] = field(default_factory=dict)

    # All parsed key-value pairs
    all_values: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# PAYLOAD PARSER
# =============================================================================

class PayloadParser:
    """Parser for MQTT telemetry payload"""

    def __init__(self):
        self.position = 0
        self.data = b''

    def _read_uint16(self) -> int:
        """Read 2-byte unsigned integer and advance position"""
        if self.position + 2 > len(self.data):
            return 0
        value = bytes_to_uint16_be(self.data[self.position], self.data[self.position + 1])
        self.position += 2
        return value

    def parse_params_list(self, data: bytes) -> ParamsListBean:
        """Parse telemetry payload into ParamsListBean"""
        if not data:
            return ParamsListBean()

        self.data = data
        self.position = 0

        result = ParamsListBean()
        result.segment_count = self._read_uint16()

        for _ in range(result.segment_count):
            if self.position + 8 > len(self.data):
                break

            segment = ParamSegment()
            segment.segment_id = self._read_uint16()
            segment.segment_type = self._read_uint16()
            segment.segment_address = self._read_uint16()
            segment.params_num = self._read_uint16()

            value_bytes = segment.params_num * 2
            if self.position + value_bytes <= len(self.data):
                segment.values = self.data[self.position:self.position + value_bytes]
                self.position += value_bytes

            result.segments.append(segment)

        return result


# =============================================================================
# VALUE PARSER
# =============================================================================

class ValueParser:
    """Parser for individual register values"""

    @staticmethod
    def parse_value(
        data: bytes,
        data_type: str = "signed",
        coefficient: str = "1",
        length: int = 1
    ) -> Any:
        """Parse raw bytes into a typed value"""
        if not data or len(data) < 2:
            return 0

        # Parse based on data length
        if length == 1:
            # Single register (2 bytes)
            if data_type == "unsigned":
                raw_value = bytes_to_uint16_be(data[0], data[1])
            else:
                raw_value = bytes_to_int16_be(data[0], data[1])
        elif length == 2:
            # Double register (4 bytes)
            if len(data) < 4:
                return 0
            if data_type == "unsigned":
                raw_value = bytes_to_uint32_be(data)
            else:
                raw_value = bytes_to_int32_be(data)
        else:
            return 0

        # Apply coefficient
        try:
            coeff = Decimal(coefficient)
            if coeff != 1:
                return float(Decimal(str(raw_value)) * coeff)
        except (ValueError, TypeError):
            pass

        return raw_value


# =============================================================================
# TELEMETRY PARSER
# =============================================================================

class ESYTelemetryParser:
    """Main parser for incoming MQTT telemetry messages"""

    def __init__(self, device_type: int = 1):
        """
        Initialize parser

        Args:
            device_type: 1 for single phase, 3 for three phase
        """
        self.device_type = device_type
        self.payload_parser = PayloadParser()
        self.value_parser = ValueParser()
        self._key_to_address_map: Dict[str, int] = {}

    def parse_message(self, payload: bytes) -> Optional[TelemetryData]:
        """
        Parse complete MQTT message (header + payload)

        Args:
            payload: Raw MQTT message bytes

        Returns:
            TelemetryData object with parsed values, or None on error
        """
        if not payload or len(payload) < HEADER_SIZE:
            _LOGGER.debug("Payload too short")
            return None

        # Parse header
        header = MsgHeader.from_bytes(payload[:HEADER_SIZE])
        if header is None:
            _LOGGER.debug("Failed to parse header")
            return None

        _LOGGER.debug(
            f"Header: funCode={header.fun_code}, dataLength={header.data_length}"
        )

        # Extract data portion
        data_start = HEADER_SIZE
        data_end = data_start + header.data_length
        if data_end > len(payload):
            data_end = len(payload)

        data = payload[data_start:data_end]

        # Parse segments
        params = self.payload_parser.parse_params_list(data)

        return self._build_telemetry_data(params)

    def _build_telemetry_data(self, params: ParamsListBean) -> TelemetryData:
        """Build TelemetryData from parsed segments"""
        result = TelemetryData()
        all_values: Dict[str, Any] = {}

        for segment in params.segments:
            self._parse_segment_values(segment, all_values)

        # Map parsed values to TelemetryData fields
        result.all_values = all_values

        # Power values
        result.pv1_power = int(all_values.get("pv1Power", 0))
        result.pv2_power = int(all_values.get("pv2Power", 0))
        result.pv_power = result.pv1_power + result.pv2_power
        result.battery_power = int(all_values.get("batteryPower", 0))
        result.ct1_power = int(all_values.get("ct1Power", 0))
        result.ct2_power = int(all_values.get("ct2Power", 0))
        result.load_power = int(all_values.get("loadRealTimePower", 0))
        result.grid_power = result.ct1_power

        # Energy flow
        result.energy_flow_pv_total_power = int(all_values.get("energyFlowPvTotalPower", result.pv_power))
        result.energy_flow_batt_power = int(all_values.get("energyFlowBattPower", result.battery_power))
        result.energy_flow_grid_power = int(all_values.get("energyFlowGridPower", result.grid_power))
        result.energy_flow_load_total_power = int(all_values.get("energyFlowLoadTotalPower", result.load_power))

        # Status
        result.on_off_grid_mode = int(all_values.get("onOffGridMode", 0))
        result.system_run_mode = int(all_values.get("systemRunMode", 0))
        result.system_run_status = int(all_values.get("systemRunStatus", 0))
        result.battery_status = int(all_values.get("batteryStatus", 0))
        result.grid_status = int(all_values.get("gridStatus", 0))
        result.inv_status = int(all_values.get("invStatus", 0))

        # Battery
        result.battery_soc = int(all_values.get("battTotalSoc", all_values.get("batterySoc", 0)))
        result.battery_voltage = float(all_values.get("batteryVoltage", 0))
        result.battery_current = float(all_values.get("batteryCurrent", 0))
        result.batt_num = int(all_values.get("battNum", 0))

        # PV details
        result.pv1_voltage = float(all_values.get("pv1voltage", 0))
        result.pv1_current = float(all_values.get("pv1current", 0))
        result.pv2_voltage = float(all_values.get("pv2voltage", 0))
        result.pv2_current = float(all_values.get("pv2current", 0))

        # Grid details
        result.grid_voltage = float(all_values.get("gridVolt", 0))
        result.grid_frequency = float(all_values.get("gridFreq", 0))

        # Inverter details
        result.inv_temperature = int(all_values.get("invTemperature", 0))
        result.inv_output_voltage = float(all_values.get("invOutputVolt", 0))
        result.inv_output_frequency = float(all_values.get("invOutputFreq", 0))

        # Energy statistics
        result.daily_energy_generation = float(all_values.get("dailyEnergyGeneration", 0))
        result.total_energy_generation = float(all_values.get("totalEnergyGeneration", 0))
        result.daily_power_consumption = float(all_values.get("dailyPowerConsumption", 0))
        result.total_power_consumption = float(all_values.get("totalEconsumption", 0))
        result.daily_batt_charge_energy = float(all_values.get("dailyBattChargeEnergy", 0))
        result.daily_batt_discharge_energy = float(all_values.get("dailyBattDischargeEnergy", 0))
        result.daily_grid_import = float(all_values.get("dailyOnGridElecConsumption", 0))
        result.daily_grid_export = float(all_values.get("dailyGridConnectionPower", 0))

        # Other
        result.rated_power = int(all_values.get("ratedPower", all_values.get("outputRatedPower", 0)))
        result.anti_backflow_percentage = int(all_values.get("antiBackflowPowerPercentage", 0))
        result.heating_state = int(all_values.get("heatingState", 0))

        return result

    def _parse_segment_values(
        self,
        segment: ParamSegment,
        all_values: Dict[str, Any]
    ) -> None:
        """Parse values from a single segment"""
        # This is a simplified implementation
        # In a full implementation, you'd map segment_address to specific keys
        # For now, we'll store raw values with address-based keys

        for i in range(segment.params_num):
            offset = i * 2
            if offset + 2 <= len(segment.values):
                raw_bytes = segment.values[offset:offset+2]
                addr = segment.segment_address + i

                # Store as signed value by default
                value = bytes_to_int16_be(raw_bytes[0], raw_bytes[1])
                all_values[f"reg_{addr}"] = value


# =============================================================================
# COMMAND BUILDER
# =============================================================================

class ESYCommandBuilder:
    """Builder for commands to send to the inverter"""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.user_id_bytes = user_id_to_bytes(user_id)
        self._msg_id_counter = 0

    def _get_next_msg_id(self) -> int:
        self._msg_id_counter += 1
        return self._msg_id_counter

    def build_write_command(
        self,
        register_address: int,
        value: int,
        config_id: int = 0
    ) -> bytes:
        """
        Build a write command to send to the inverter

        Args:
            register_address: The register address to write to
            value: The value to write (16-bit)
            config_id: Configuration ID (usually 0)

        Returns:
            Complete message bytes to publish to DOWN topic
        """
        # Build payload: address (2 bytes) + value (2 bytes)
        payload = bytearray()
        payload.extend(int16_to_bytes_be(register_address))
        payload.extend(int16_to_bytes_be(value & 0xFFFF))

        # Build header
        header = MsgHeader(
            config_id=config_id,
            msg_id=self._get_next_msg_id(),
            user_id=self.user_id_bytes,
            fun_code=FunctionCode.WRITE_SINGLE,
            source_id=0x02,  # App source
            page_index=0,
            data_length=len(payload)
        )

        return header.to_bytes() + bytes(payload)

    def build_read_command(
        self,
        register_address: int,
        register_count: int = 1,
        config_id: int = 0
    ) -> bytes:
        """
        Build a read command to request data from the inverter

        Args:
            register_address: The starting register address
            register_count: Number of registers to read
            config_id: Configuration ID

        Returns:
            Complete message bytes to publish to DOWN topic
        """
        # Build payload: address (2 bytes) + count (2 bytes)
        payload = bytearray()
        payload.extend(int16_to_bytes_be(register_address))
        payload.extend(int16_to_bytes_be(register_count))

        # Build header
        header = MsgHeader(
            config_id=config_id,
            msg_id=self._get_next_msg_id(),
            user_id=self.user_id_bytes,
            fun_code=FunctionCode.READ,
            source_id=0x02,
            page_index=0,
            data_length=len(payload)
        )

        return header.to_bytes() + bytes(payload)


# =============================================================================
# MQTT TOPIC HELPERS
# =============================================================================

def get_mqtt_topics(device_id: str) -> Dict[str, str]:
    """Get MQTT topics for a device"""
    return {
        "up": f"/ESY/PVVC/{device_id}/UP",
        "down": f"/ESY/PVVC/{device_id}/DOWN",
        "alarm": f"/ESY/PVVC/{device_id}/ALARM",
    }


def get_user_news_topic(user_id: str) -> str:
    """Get the user news topic for push notifications"""
    return f"/APP/{user_id}/NEWS"

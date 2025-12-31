"""
ESY SunHome / BenBen Energy Inverter - MQTT Binary Protocol Parser

This module provides complete parsing logic for the binary MQTT protocol used by the ESY HM6 inverter.

MQTT Topics:
- /ESY/PVVC/{device_id}/UP    - Telemetry FROM inverter (subscribe)
- /ESY/PVVC/{device_id}/DOWN  - Commands TO inverter (publish)
- /ESY/PVVC/{device_id}/ALARM - Alarm messages (subscribe)

MQTT Brokers (Only the international one will be used):
- tcp://abroadtcp.esysunhome.com:1883
"""

import struct
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, Union
from enum import IntEnum
from decimal import Decimal


# =============================================================================
# CONSTANTS
# =============================================================================

MQTT_BROKER_INTERNATIONAL = "tcp://abroadtcp.esysunhome.com:1883"
MQTT_BROKER_DOMESTIC = "tcp://120.79.138.205:1883"

HEADER_SIZE = 24  # 0x18 bytes


class FunctionCode(IntEnum):
    """MQTT message function codes"""
    READ = 0x03
    WRITE_SINGLE = 0x06
    WRITE_MULTIPLE = 0x10
    RESPONSE = 0x83


class DataType(IntEnum):
    """Data type codes for value parsing"""
    DEFAULT = 0          # 2-byte signed/unsigned based on dataType field
    SIGNED_16 = 1        # 2-byte signed
    UNSIGNED_16 = 2      # 2-byte unsigned  
    SIGNED_32 = 3        # 4-byte signed (uses 2 registers)
    STRING_VAR = 4       # Variable length string (first byte = length)
    STRING_FIXED = 5     # Fixed length string
    BYTE_ARRAY = 6       # Raw byte array (reversed pairs)
    DATE_TIME = 100      # Date/time format


class ByteTruncate(IntEnum):
    """Special byte truncation modes"""
    NONE = 0
    HIGH_BYTE = 1        # Use high byte only
    LOW_BYTE = 2         # Use low byte only
    DATE_FORMAT = 7      # Date: year offset by 15
    SPECIAL_8 = 8        # Skip processing
    SPECIAL_10 = 10      # Skip processing


# =============================================================================
# BYTE CONVERSION UTILITIES (from ByteIntUtils.smali)
# =============================================================================

def bytes_to_int32_be(data: bytes) -> int:
    """
    Convert 4 bytes to signed 32-bit integer (big-endian)
    Equivalent to ByteIntUtils.a([B)I
    """
    if len(data) < 4:
        return 0
    # bytes[3] | (bytes[2] << 8) | (bytes[1] << 16) | (bytes[0] << 24)
    return struct.unpack('>i', data[:4])[0]


def bytes_to_uint32_be(data: bytes) -> int:
    """
    Convert 4 bytes to unsigned 32-bit integer (big-endian)
    Equivalent to ByteIntUtils.b([B)I
    """
    if len(data) < 4:
        return 0
    b0 = data[0] & 0xFF
    b1 = data[1] & 0xFF
    b2 = data[2] & 0xFF
    b3 = data[3] & 0xFF
    return (b3) | (b2 << 8) | (b1 << 16) | (b0 << 24)


def bytes_to_int32_be_alt(data: bytes) -> int:
    """
    Alternative 32-bit conversion (standard big-endian)
    Equivalent to ByteIntUtils.c([B)I
    """
    if len(data) < 4:
        return 0
    return struct.unpack('>i', data[:4])[0]


def bytes_to_uint16_be(b0: int, b1: int) -> int:
    """
    Convert 2 bytes to unsigned 16-bit integer
    Equivalent to ByteIntUtils.d(BB)I
    """
    return ((b0 & 0xFF) << 8) | (b1 & 0xFF)


def bytes_to_int16_be(b0: int, b1: int) -> int:
    """
    Convert 2 bytes to signed 16-bit integer
    Equivalent to ByteIntUtils.e(BB)I
    """
    value = (b0 << 8) | (b1 & 0xFF)
    if value >= 0x8000:
        value -= 0x10000
    return value


def parse_bytes_with_type(data: bytes, data_type: Optional[str] = None) -> int:
    """
    Parse bytes based on data type string
    Equivalent to ByteIntUtils.f([BLjava/lang/String;)I
    
    Args:
        data: byte array (2 or 4 bytes)
        data_type: "signed", "unsigned", or None
    """
    if data_type is None:
        if len(data) == 2:
            return bytes_to_int16_be(data[0], data[1])
        elif len(data) == 4:
            return bytes_to_int32_be_alt(data)
        return 0
    
    if data_type == "unsigned":
        if len(data) == 2:
            return bytes_to_uint16_be(data[0], data[1])
        elif len(data) == 4:
            return bytes_to_uint32_be(data)
    elif data_type == "signed":
        if len(data) == 2:
            return bytes_to_int16_be(data[0], data[1])
        elif len(data) == 4:
            return bytes_to_int32_be_alt(data)
    
    return 0


def int32_to_bytes_be(value: int) -> bytes:
    """
    Convert 32-bit integer to 4 bytes (big-endian)
    Equivalent to ByteIntUtils.i(I)[B
    """
    return struct.pack('>i', value)


def int16_to_bytes_be(value: int) -> bytes:
    """
    Convert 16-bit integer to 2 bytes (big-endian)
    Equivalent to ByteIntUtils.k(I)[B
    """
    return bytes([(value >> 8) & 0xFF, value & 0xFF])


def user_id_to_bytes(user_id: str) -> bytes:
    """
    Convert user ID string to 8-byte array
    Equivalent to ByteIntUtils.g(Ljava/lang/String;)[B
    """
    result = bytearray(8)
    if not user_id or not user_id.isdigit():
        return bytes(result)
    
    try:
        value = int(user_id)
        binary = bin(value)[2:]  # Remove '0b' prefix
        # Pad to multiple of 8 bits
        padding = (8 - len(binary) % 8) % 8
        binary = '0' * padding + binary
        
        # Convert to bytes (fill from end)
        byte_count = len(binary) // 8
        for i in range(byte_count):
            start = i * 8
            end = start + 8
            result[7 - (byte_count - 1 - i)] = int(binary[start:end], 2)
    except (ValueError, OverflowError):
        pass
    
    return bytes(result)


# =============================================================================
# MESSAGE HEADER (from MsgHeaderBean.smali and MqttUtils.smali)
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
        """
        Parse header from byte array
        Equivalent to MqttUtils.j([B)Lcom/lucky/mqttlib/bean/MsgHeaderBean
        """
        if data is None or len(data) < HEADER_SIZE:
            return None
        
        # configId: bytes 0-3
        config_id = bytes_to_uint32_be(data[0:4])
        
        # msgId: bytes 4-7
        msg_id = bytes_to_uint32_be(data[4:8])
        
        # userId: bytes 8-15
        user_id = data[8:16]
        
        # funCode: byte 16
        fun_code = data[16] & 0xFF
        
        # sourceId: byte 17 (value is stored shifted left by 4)
        source_id = data[17] & 0xFF
        
        # pageIndex: byte 18
        page_index = data[18] & 0xFF
        
        # dataLength: bytes 22-23
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
        """
        Serialize header to byte array
        Equivalent to MqttUtils.b(Lcom/lucky/mqttlib/bean/MsgHeaderBean)[B
        """
        result = bytearray(HEADER_SIZE)
        
        # configId: bytes 0-3
        result[0:4] = int32_to_bytes_be(self.config_id)
        
        # msgId: bytes 4-7 (typically 0 for outgoing)
        result[4:8] = int32_to_bytes_be(self.msg_id)
        
        # userId: bytes 8-15
        user_bytes = self.user_id if isinstance(self.user_id, bytes) else bytes(8)
        result[8:16] = user_bytes[:8].ljust(8, b'\x00')
        
        # funCode: byte 16
        result[16] = self.fun_code & 0xFF
        
        # sourceId: byte 17 (shifted left by 4)
        result[17] = (self.source_id << 4) & 0xFF
        
        # pageIndex: byte 18
        result[18] = self.page_index & 0xFF
        
        # reserved: bytes 19-21
        result[19:22] = b'\x00\x00\x00'
        
        # dataLength: bytes 22-23
        result[22:24] = int16_to_bytes_be(self.data_length)
        
        return bytes(result)


# =============================================================================
# PARAMETER SEGMENT (from ParamSegmentBean.smali)
# =============================================================================

@dataclass
class ParamSegment:
    """
    Parameter segment within telemetry payload
    
    Each segment contains a contiguous block of register values
    """
    segment_id: int = 0
    segment_type: int = 0
    segment_address: int = 0  # Starting register address
    params_num: int = 0       # Number of parameters (registers)
    values: bytes = field(default_factory=bytes)  # Raw register values
    
    def get_register_value(self, offset: int, length: int = 2) -> bytes:
        """Get raw bytes for a register at offset"""
        start = offset * 2
        end = start + length
        if end <= len(self.values):
            return self.values[start:end]
        return bytes(length)


@dataclass
class ParamsListBean:
    """
    Container for all parameter segments
    Equivalent to ParamsListBean.smali
    """
    segment_count: int = 0
    segments: List[ParamSegment] = field(default_factory=list)


# =============================================================================
# KEY VALUE DTO (from KeyValueDTO.smali)
# =============================================================================

@dataclass
class KeyValueDTO:
    """
    Data transfer object for a single parameter/register
    
    Contains metadata about how to parse and interpret the value
    """
    key: str = ""                    # Parameter name (e.g., "batteryPower")
    label: str = ""                  # Display label
    val: str = ""                    # Parsed value as string
    unit: str = ""                   # Unit (e.g., "W", "V", "%")
    address_array: List[int] = field(default_factory=list)  # Register addresses
    data_length: int = 2             # 1=2bytes, 2=4bytes, 3=special
    data_type: str = "signed"        # "signed" or "unsigned"
    coefficient: Decimal = field(default_factory=lambda: Decimal("1"))  # Multiplier
    byte_truncate: int = 0           # Special parsing mode
    segment_id: int = 0              # Which segment this belongs to
    data_bytes: bytes = field(default_factory=bytes)  # Raw bytes


# =============================================================================
# TELEMETRY KEYS AND REGISTER MAPPINGS
# Extracted from SegmentKeyManager.smali
# =============================================================================

# Energy flow display keys (used for main dashboard)
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

ENERGY_FLOW_KEYS_THREE_PHASE = [
    "energyFlowLoadTotalPower", "bmsOnlineNumber", "onOffGridMode",
    "antiBackflowPowerPercentage", "systemRunMode", "batteryStatus",
    "battTotalSoc", "pv1Power", "pv2Power", "energyFlowDiagramLineFlag1",
    "energyFlowDiagramLineFlag2", "systemRunStatus", "outputRatedPower",
    "dailyEnergyGeneration", "energyFlowPvTotalPower", "totalPowerOfBatteryInFlow",
    "totalPowerOfGridInFlow"
]

# Complete parameter definitions grouped by category
# Format: {key: {"address": [addresses], "length": data_length, "type": data_type, "coeff": coefficient, "unit": unit}}

REGISTER_DEFINITIONS = {
    # =========================================================================
    # RUN INFORMATION
    # =========================================================================
    "displayType": {"length": 1, "type": "unsigned"},
    "mcuSoftwareVer": {"length": 1, "type": "unsigned"},
    "dspSoftwareVer": {"length": 1, "type": "unsigned"},
    "mcuHardwareVer": {"length": 1, "type": "unsigned"},
    "dspHardwareVer": {"length": 1, "type": "unsigned"},
    "systemRunMode": {"length": 1, "type": "unsigned", "unit": ""},
    "systemRunStatus": {"length": 1, "type": "unsigned", "unit": ""},
    
    # =========================================================================
    # BASIC INFORMATION
    # =========================================================================
    "dcdcTemperature": {"length": 1, "type": "signed", "unit": "°C"},
    "countryCode": {"length": 1, "type": "unsigned"},
    "busVoltage": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "V"},
    "dailyEnergyGeneration": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "kWh"},
    "totalEnergyGeneration": {"length": 2, "type": "unsigned", "coeff": "0.1", "unit": "kWh"},
    "ratedPower": {"length": 1, "type": "unsigned", "unit": "W"},
    "battCapacity": {"length": 1, "type": "unsigned", "unit": "Ah"},
    
    # =========================================================================
    # PV INFORMATION
    # =========================================================================
    "pv1voltage": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "V"},
    "pv1current": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "A"},
    "pv1Power": {"length": 1, "type": "unsigned", "unit": "W"},
    "pv2voltage": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "V"},
    "pv2current": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "A"},
    "pv2Power": {"length": 1, "type": "unsigned", "unit": "W"},
    "pvIsoVoltage": {"length": 1, "type": "unsigned", "coeff": "0.001", "unit": "MΩ"},
    
    # =========================================================================
    # BATTERY INFORMATION
    # =========================================================================
    "batteryStatus": {"length": 1, "type": "unsigned"},
    "batteryVoltage": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "V"},
    "batteryCurrent": {"length": 1, "type": "signed", "coeff": "0.1", "unit": "A"},
    "batteryPower": {"length": 1, "type": "signed", "unit": "W"},
    "battTotalSoc": {"length": 1, "type": "unsigned", "unit": "%"},
    "batterySoc": {"length": 1, "type": "unsigned", "unit": "%"},
    "battSign": {"length": 1, "type": "unsigned"},
    "battChgVolt": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "V"},
    "battNum": {"length": 1, "type": "unsigned"},
    "battEnergy": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "kWh"},
    "battCellVoltMax": {"length": 1, "type": "unsigned", "coeff": "0.001", "unit": "V"},
    "battCellVoltMin": {"length": 1, "type": "unsigned", "coeff": "0.001", "unit": "V"},
    "battWorkState": {"length": 1, "type": "unsigned"},
    
    # =========================================================================
    # GRID INFORMATION
    # =========================================================================
    "gridStatus": {"length": 1, "type": "unsigned"},
    "gridFreq": {"length": 1, "type": "unsigned", "coeff": "0.01", "unit": "Hz"},
    "gridVolt": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "V"},
    "sampleGridVolt": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "V"},
    "gridApparentPower": {"length": 1, "type": "signed", "unit": "VA"},
    "gridActivePower": {"length": 1, "type": "signed", "unit": "W"},
    "gridReactivePower": {"length": 1, "type": "signed", "unit": "var"},
    "ct1Curr": {"length": 1, "type": "signed", "coeff": "0.1", "unit": "A"},
    "ct1Power": {"length": 1, "type": "signed", "unit": "W"},
    "ct2Curr": {"length": 1, "type": "signed", "coeff": "0.1", "unit": "A"},
    "ct2Power": {"length": 1, "type": "signed", "unit": "W"},
    "onOffGridMode": {"length": 1, "type": "unsigned"},
    
    # =========================================================================
    # INVERTER INFORMATION
    # =========================================================================
    "invTemperature": {"length": 1, "type": "signed", "unit": "°C"},
    "invStatus": {"length": 1, "type": "unsigned"},
    "invOutputFreq": {"length": 1, "type": "unsigned", "coeff": "0.01", "unit": "Hz"},
    "invOutputVolt": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "V"},
    "invOutputCurr": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "A"},
    "invApparentPower": {"length": 1, "type": "signed", "unit": "VA"},
    "invActivePower": {"length": 1, "type": "signed", "unit": "W"},
    "invReactivePower": {"length": 1, "type": "signed", "unit": "var"},
    "outputRatedPower": {"length": 1, "type": "unsigned", "unit": "W"},
    
    # =========================================================================
    # ENERGY FLOW
    # =========================================================================
    "energyFlowPvTotalPower": {"length": 1, "type": "signed", "unit": "W"},
    "energyFlowBattPower": {"length": 1, "type": "signed", "unit": "W"},
    "energyFlowGridPower": {"length": 1, "type": "signed", "unit": "W"},
    "energyFlowLoadTotalPower": {"length": 1, "type": "signed", "unit": "W"},
    "totalPowerOfBatteryInFlow": {"length": 1, "type": "signed", "unit": "W"},
    "totalPowerOfGridInFlow": {"length": 1, "type": "signed", "unit": "W"},
    "energyFlowChartLineNumber1to8": {"length": 1, "type": "unsigned"},
    "energyFlowChartLineNumber9to16": {"length": 1, "type": "unsigned"},
    "energyFlowChartLineNumber1to16": {"length": 2, "type": "unsigned"},
    "energyFlowChartLineSegmentMarkerApp": {"length": 1, "type": "unsigned"},
    "energyFlowDiagramLineFlag1": {"length": 1, "type": "unsigned"},
    "energyFlowDiagramLineFlag2": {"length": 1, "type": "unsigned"},
    
    # =========================================================================
    # LOAD INFORMATION
    # =========================================================================
    "loadVolt": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "V"},
    "loadCurr": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "A"},
    "loadActivePower": {"length": 1, "type": "signed", "unit": "W"},
    "loadRealTimePower": {"length": 1, "type": "signed", "unit": "W"},
    "loadPowerPercentage": {"length": 1, "type": "unsigned", "unit": "%"},
    "apparentPower": {"length": 1, "type": "signed", "unit": "VA"},
    
    # =========================================================================
    # ENERGY STATISTICS
    # =========================================================================
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
    
    # =========================================================================
    # SETTINGS (READABLE/WRITABLE)
    # =========================================================================
    "antiBackflowPowerPercentage": {"length": 1, "type": "unsigned", "unit": "%"},
    "batteryChargingCurrent": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "A"},
    "batteryDischargeCurrent": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "A"},
    "batteryAverageChargeVoltage": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "V"},
    "batteryFloatChargeVoltage": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "V"},
    "batteryEod": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "V"},
    "batteryDod": {"length": 1, "type": "unsigned", "unit": "%"},
    "onGridSocLimit": {"length": 1, "type": "unsigned", "unit": "%"},
    "offGridSocLimit": {"length": 1, "type": "unsigned", "unit": "%"},
    "battRatedCapacity": {"length": 1, "type": "unsigned", "unit": "Ah"},
    "batteryType": {"length": 1, "type": "unsigned"},
    
    # =========================================================================
    # SYSTEM STATUS
    # =========================================================================
    "faultStatus": {"length": 1, "type": "unsigned"},
    "selfTestStatus": {"length": 1, "type": "unsigned"},
    "usbStatus": {"length": 1, "type": "unsigned"},
    "upgradeProgress": {"length": 1, "type": "unsigned", "unit": "%"},
    "runTimeDays": {"length": 1, "type": "unsigned", "unit": "days"},
    "runTimeHours": {"length": 1, "type": "unsigned", "unit": "h"},
    "runTimeMinutes": {"length": 1, "type": "unsigned", "unit": "min"},
    "runTimeSecond": {"length": 1, "type": "unsigned", "unit": "s"},
    
    # =========================================================================
    # METER INFORMATION
    # =========================================================================
    "meterIdentifier": {"length": 1, "type": "unsigned"},
    "meterNormalSign": {"length": 1, "type": "unsigned"},
    "meterVolt": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "V"},
    "meterCurr": {"length": 1, "type": "signed", "coeff": "0.001", "unit": "A"},
    "meterPower": {"length": 1, "type": "signed", "unit": "W"},
    "meterPowerFactor": {"length": 1, "type": "unsigned", "coeff": "0.001"},
    "meterFreq": {"length": 1, "type": "unsigned", "coeff": "0.01", "unit": "Hz"},
    
    # =========================================================================
    # TEMPERATURE
    # =========================================================================
    "pvTemperature": {"length": 1, "type": "signed", "unit": "°C"},
    "internalTemperature": {"length": 1, "type": "signed", "unit": "°C"},
    "ambientTemp": {"length": 1, "type": "signed", "unit": "°C"},
    "heatingState": {"length": 1, "type": "unsigned"},
    "battHeatStatus": {"length": 1, "type": "unsigned"},
    
    # =========================================================================
    # BMS INFORMATION
    # =========================================================================
    "bmsOnlineNumber": {"length": 1, "type": "unsigned"},
    "bmsCommStatus": {"length": 1, "type": "unsigned"},
    "maxChgThreshold": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "A"},
    "maxDhgThreshold": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "A"},
    "soc": {"length": 1, "type": "unsigned", "unit": "%"},
    "soh": {"length": 1, "type": "unsigned", "unit": "%"},
    "highestTemperature": {"length": 1, "type": "signed", "unit": "°C"},
    "lowestTemperature": {"length": 1, "type": "signed", "unit": "°C"},
    "maxCellVolt": {"length": 1, "type": "unsigned", "coeff": "0.001", "unit": "V"},
    "minCellVolt": {"length": 1, "type": "unsigned", "coeff": "0.001", "unit": "V"},
    
    # =========================================================================
    # GENERATOR
    # =========================================================================
    "generatorStatus": {"length": 1, "type": "unsigned"},
    "generatorMode": {"length": 1, "type": "unsigned"},
    "generatorStartBattVolt": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "V"},
    "generatorStartBattSoc": {"length": 1, "type": "unsigned", "unit": "%"},
    "generatorEndBattVolt": {"length": 1, "type": "unsigned", "coeff": "0.1", "unit": "V"},
    "generatorEndBattSoc": {"length": 1, "type": "unsigned", "unit": "%"},
    "generatorRatePower": {"length": 1, "type": "unsigned", "unit": "W"},
    
    # =========================================================================
    # SPECIAL CELL VOLTAGE KEYS (use coefficient 0.05 with offset)
    # =========================================================================
    "powerDownVoltage": {"length": 1, "type": "unsigned", "coeff": "0.05", "special": "cell_voltage"},
    "cellOverDischargeProtection": {"length": 1, "type": "unsigned", "coeff": "0.05", "special": "cell_voltage"},
    "cellOverDischargeAlarmVoltage": {"length": 1, "type": "unsigned", "coeff": "0.1", "special": "cell_voltage_alt"},
}


# =============================================================================
# MQTT DEVICE INFO (from MqttDeviceInfoVo.smali)
# =============================================================================

@dataclass
class MqttDeviceInfoVo:
    """
    Parsed telemetry data object
    Contains all the key values from energy flow display
    """
    # Power values
    pv_power: int = 0
    pv1_power: int = 0
    pv2_power: int = 0
    battery_power: int = 0
    ct1_power: int = 0
    ct2_power: int = 0
    load_real_time_power: int = 0
    energy_flow_pv_total_power: int = 0
    energy_flow_batt_power: int = 0
    energy_flow_grid_power: int = 0
    energy_flow_load_total_power: int = 0
    total_power_of_battery_in_flow: int = 0
    total_power_of_grid_in_flow: int = 0
    
    # Status values
    on_off_grid_mode: int = 0
    system_run_mode: int = 0
    system_run_status: int = 0
    battery_status: int = 0
    status: int = 0
    
    # Battery
    batt_total_soc: int = 0
    batt_num: int = 0
    bms_online_number: int = 0
    
    # Other
    anti_backflow_power_percentage: int = 0
    rated_power: int = 0
    output_rated_power: int = 0
    daily_energy_generation: int = 0
    
    # Line diagram flags
    energy_flow_chart_line_1to8: int = 0
    energy_flow_chart_line_9to16: int = 0
    energy_flow_diagram_line_flag1: int = 0
    energy_flow_diagram_line_flag2: int = 0
    
    # All parsed values as dict
    all_values: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# PAYLOAD PARSER (from MqttUtils.smali and MqttDeviceDetailParsing.smali)
# =============================================================================

class PayloadParser:
    """
    Parser for MQTT telemetry payload
    
    Payload structure:
    - 2 bytes: segment count
    - For each segment:
      - 2 bytes: segment_id
      - 2 bytes: segment_type
      - 2 bytes: segment_address (starting register)
      - 2 bytes: params_num (number of registers)
      - params_num * 2 bytes: register values
    """
    
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
        """
        Parse telemetry payload into ParamsListBean
        Equivalent to MqttUtils.l([B)Lcom/lucky/mqttlib/bean/ParamsListBean
        """
        if not data:
            return ParamsListBean()
        
        self.data = data
        self.position = 0
        
        result = ParamsListBean()
        
        # Read segment count
        result.segment_count = self._read_uint16()
        
        # Parse each segment
        for _ in range(result.segment_count):
            if self.position + 8 > len(self.data):
                break
            
            segment = ParamSegment()
            segment.segment_id = self._read_uint16()
            segment.segment_type = self._read_uint16()
            segment.segment_address = self._read_uint16()
            segment.params_num = self._read_uint16()
            
            # Read register values
            value_bytes = segment.params_num * 2
            if self.position + value_bytes <= len(self.data):
                segment.values = self.data[self.position:self.position + value_bytes]
                self.position += value_bytes
            
            result.segments.append(segment)
        
        return result


class ValueParser:
    """
    Parser for individual register values
    Based on MqttDeviceDetailParsing methods
    """
    
    @staticmethod
    def parse_value(data: bytes, dto: KeyValueDTO) -> str:
        """
        Parse bytes into value string based on KeyValueDTO configuration
        Equivalent to MqttDeviceDetailParsing.g() and related methods
        """
        if not data:
            return "0"
        
        data_length = dto.data_length
        byte_truncate = dto.byte_truncate
        coefficient = dto.coefficient
        data_type = dto.data_type
        
        # Handle different data lengths
        if data_length == 1:  # Single register (2 bytes)
            return ValueParser._parse_single_register(data, coefficient, data_type, byte_truncate)
        elif data_length == 2:  # Double register (4 bytes)
            return ValueParser._parse_double_register(data, coefficient, data_type)
        elif data_length == 3:  # Special formats (date/time)
            return ValueParser._parse_special_format(data, byte_truncate)
        elif data_length >= 4:  # String or byte array
            return ValueParser._parse_extended(data, data_length, byte_truncate)
        
        return "0"
    
    @staticmethod
    def _parse_single_register(data: bytes, coefficient: Decimal, data_type: str, byte_truncate: int) -> str:
        """Parse single register (2 bytes)"""
        if len(data) < 2:
            return "0"
        
        high_byte = data[0] & 0xFF
        low_byte = data[1] & 0xFF
        
        # Handle byte truncation modes
        if byte_truncate == ByteTruncate.HIGH_BYTE:
            raw_value = high_byte
        elif byte_truncate == ByteTruncate.LOW_BYTE:
            raw_value = low_byte
        else:
            # Full 16-bit value
            if data_type == "signed":
                raw_value = bytes_to_int16_be(high_byte, low_byte)
            else:
                raw_value = bytes_to_uint16_be(high_byte, low_byte)
        
        # Apply coefficient
        result = Decimal(raw_value) * coefficient
        return str(result)
    
    @staticmethod
    def _parse_double_register(data: bytes, coefficient: Decimal, data_type: str) -> str:
        """Parse double register (4 bytes / 32-bit)"""
        if len(data) < 4:
            return "0"
        
        if data_type == "signed":
            raw_value = bytes_to_int32_be(data[:4])
        else:
            raw_value = bytes_to_uint32_be(data[:4])
        
        result = Decimal(raw_value) * coefficient
        return str(result)
    
    @staticmethod
    def _parse_special_format(data: bytes, byte_truncate: int) -> str:
        """Parse special formats like dates"""
        if len(data) < 4:
            return ""
        
        if byte_truncate == ByteTruncate.DATE_FORMAT:
            # Date format: year (offset +15), month (+1), day (+1)
            year = (data[1] & 0xFF) + 15
            month = (data[2] & 0xFF) + 1
            day = (data[3] & 0xFF) + 1
            return f"{year}-{month}-{day}"
        else:
            # Default: show as hyphen-separated values
            return f"{data[0]}-{data[1]}-{data[2]}"
    
    @staticmethod
    def _parse_extended(data: bytes, data_length: int, byte_truncate: int) -> str:
        """Parse extended formats (strings, byte arrays)"""
        if data_length == 4 or data_length == 5:
            # Variable length string (first byte is length)
            str_len = data[0] if data else 0
            if str_len > 0 and len(data) > str_len:
                return data[1:1+str_len].decode('utf-8', errors='ignore')
        elif data_length == 6:
            # Byte array with reversed pairs
            result = bytearray()
            for i in range(0, len(data), 2):
                if i + 1 < len(data):
                    b1 = data[i]
                    b2 = data[i + 1]
                    if b1 != 0 or b2 != 0:
                        result.append(b2)
                        result.append(b1)
            return result.decode('utf-8', errors='ignore')
        elif byte_truncate == 100:
            # DateTime format
            return ''.join(f'{b:02d}' for b in data)
        
        # Fallback: raw string
        return data.decode('utf-8', errors='ignore').rstrip('\x00')


# =============================================================================
# MAIN TELEMETRY PARSER
# =============================================================================

class ESYTelemetryParser:
    """
    Main parser for ESY/BenBen inverter telemetry
    
    Usage:
        parser = ESYTelemetryParser()
        
        # Parse incoming MQTT message
        result = parser.parse_message(mqtt_payload)
        
        # Access parsed values
        print(result.all_values)
        print(result.battery_power)
    """
    
    def __init__(self, device_type: int = 1):
        """
        Initialize parser
        
        Args:
            device_type: 1 = single phase, 3 = three phase
        """
        self.device_type = device_type
        self.payload_parser = PayloadParser()
        
        # Select appropriate key list based on device type
        if device_type == 3:
            self.energy_flow_keys = ENERGY_FLOW_KEYS_THREE_PHASE
        else:
            self.energy_flow_keys = ENERGY_FLOW_KEYS_SINGLE_PHASE
    
    def parse_message(self, data: bytes) -> Optional[MqttDeviceInfoVo]:
        """
        Parse complete MQTT message (header + payload)
        
        Args:
            data: Raw MQTT message bytes
            
        Returns:
            MqttDeviceInfoVo with parsed values, or None on error
        """
        if not data or len(data) < HEADER_SIZE:
            return None
        
        # Parse header
        header = MsgHeader.from_bytes(data)
        if header is None:
            return None
        
        # Extract payload
        payload_start = HEADER_SIZE
        payload_end = payload_start + header.data_length
        
        if payload_end > len(data):
            payload_end = len(data)
        
        payload = data[payload_start:payload_end]
        
        # Parse payload
        return self.parse_payload(payload)
    
    def parse_payload(self, payload: bytes) -> MqttDeviceInfoVo:
        """
        Parse telemetry payload (after header)
        
        Args:
            payload: Payload bytes (without header)
            
        Returns:
            MqttDeviceInfoVo with parsed values
        """
        result = MqttDeviceInfoVo()
        
        # Parse into segments
        params_list = self.payload_parser.parse_params_list(payload)
        
        # Process each segment
        for segment in params_list.segments:
            self._process_segment(segment, result)
        
        return result
    
    def _process_segment(self, segment: ParamSegment, result: MqttDeviceInfoVo):
        """Process a single segment and extract values"""
        base_address = segment.segment_address
        
        # Iterate through register values
        for i in range(segment.params_num):
            register_address = base_address + i
            
            # Get 2-byte value at this position
            offset = i * 2
            if offset + 2 <= len(segment.values):
                raw_bytes = segment.values[offset:offset + 2]
                
                # Parse as signed 16-bit by default
                value = bytes_to_int16_be(raw_bytes[0], raw_bytes[1])
                
                # Store raw value by address
                result.all_values[f"reg_{register_address}"] = value
        
        # Also store segment info
        result.all_values[f"segment_{segment.segment_id}_address"] = segment.segment_address
        result.all_values[f"segment_{segment.segment_id}_count"] = segment.params_num
    
    def parse_with_key_mapping(self, payload: bytes, key_mapping: Dict[str, int]) -> Dict[str, Any]:
        """
        Parse payload using a custom key-to-address mapping
        
        Args:
            payload: Payload bytes
            key_mapping: Dict mapping key names to register addresses
            
        Returns:
            Dict of key -> parsed value
        """
        result = {}
        
        # Parse into segments
        params_list = self.payload_parser.parse_params_list(payload)
        
        # Build address -> value lookup
        address_values = {}
        for segment in params_list.segments:
            for i in range(segment.params_num):
                addr = segment.segment_address + i
                offset = i * 2
                if offset + 2 <= len(segment.values):
                    address_values[addr] = segment.values[offset:offset + 2]
        
        # Map keys to values
        for key, address in key_mapping.items():
            if address in address_values:
                raw_bytes = address_values[address]
                
                # Get register definition if available
                reg_def = REGISTER_DEFINITIONS.get(key, {})
                data_type = reg_def.get("type", "signed")
                coeff = Decimal(reg_def.get("coeff", "1"))
                
                # Parse value
                if data_type == "signed":
                    raw_value = bytes_to_int16_be(raw_bytes[0], raw_bytes[1])
                else:
                    raw_value = bytes_to_uint16_be(raw_bytes[0], raw_bytes[1])
                
                # Apply coefficient
                value = float(Decimal(raw_value) * coeff)
                
                # Store with unit if available
                unit = reg_def.get("unit", "")
                result[key] = {"value": value, "unit": unit, "raw": raw_value}
        
        return result


# =============================================================================
# COMMAND BUILDER
# =============================================================================

class ESYCommandBuilder:
    """
    Builder for commands to send to the inverter
    
    Usage:
        builder = ESYCommandBuilder(user_id="12345678")
        
        # Build a write command
        message = builder.build_write_command(
            register_address=100,
            value=50
        )
        
        # Publish to /ESY/PVVC/{device_id}/DOWN
    """
    
    def __init__(self, user_id: str, config_id: int = 0):
        """
        Initialize command builder
        
        Args:
            user_id: User ID string
            config_id: Configuration ID (usually 0)
        """
        self.user_id = user_id
        self.user_id_bytes = user_id_to_bytes(user_id)
        self.config_id = config_id
        self.msg_id_counter = 0
    
    def _get_next_msg_id(self) -> int:
        """Get next message ID"""
        self.msg_id_counter += 1
        return self.msg_id_counter
    
    def build_write_command(self, register_address: int, value: int,
                           fun_code: int = FunctionCode.WRITE_SINGLE) -> bytes:
        """
        Build a write command message
        
        Args:
            register_address: Target register address
            value: Value to write (16-bit)
            fun_code: Function code (default: write single)
            
        Returns:
            Complete message bytes to publish
        """
        # Build header
        header = MsgHeader(
            config_id=self.config_id,
            msg_id=self._get_next_msg_id(),
            user_id=self.user_id_bytes,
            fun_code=fun_code,
            source_id=0x02,  # App source
            page_index=0,
            data_length=4  # 2 bytes address + 2 bytes value
        )
        
        # Build payload
        payload = bytearray()
        payload.extend(int16_to_bytes_be(register_address))
        payload.extend(int16_to_bytes_be(value & 0xFFFF))
        
        # Combine
        return header.to_bytes() + bytes(payload)
    
    def build_multi_write_command(self, register_address: int, 
                                  values: List[int]) -> bytes:
        """
        Build a multi-register write command
        
        Args:
            register_address: Starting register address
            values: List of values to write
            
        Returns:
            Complete message bytes
        """
        # Build header
        payload_length = 4 + len(values) * 2  # addr(2) + count(2) + values
        
        header = MsgHeader(
            config_id=self.config_id,
            msg_id=self._get_next_msg_id(),
            user_id=self.user_id_bytes,
            fun_code=FunctionCode.WRITE_MULTIPLE,
            source_id=0x02,
            page_index=0,
            data_length=payload_length
        )
        
        # Build payload
        payload = bytearray()
        payload.extend(int16_to_bytes_be(register_address))
        payload.extend(int16_to_bytes_be(len(values)))
        for val in values:
            payload.extend(int16_to_bytes_be(val & 0xFFFF))
        
        return header.to_bytes() + bytes(payload)


# =============================================================================
# MQTT CLIENT HELPER
# =============================================================================

def get_mqtt_topics(device_id: str) -> Dict[str, str]:
    """
    Get MQTT topics for a device
    
    Args:
        device_id: Device ID string
        
    Returns:
        Dict with 'up', 'down', 'alarm' topic strings
    """
    return {
        'up': f'/ESY/PVVC/{device_id}/UP',
        'down': f'/ESY/PVVC/{device_id}/DOWN',
        'alarm': f'/ESY/PVVC/{device_id}/ALARM',
        'news': f'/APP/{device_id}/NEWS'  # Uses user_id typically
    }


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    # Example: Parse a telemetry message
    print("ESY Inverter Protocol Parser")
    print("=" * 50)
    
    # Create parser
    parser = ESYTelemetryParser(device_type=1)
    
    # Example raw message (you would get this from MQTT)
    # This is a placeholder - replace with actual captured data
    example_header = bytes([
        0x00, 0x00, 0x00, 0x01,  # configId
        0x00, 0x00, 0x00, 0x01,  # msgId
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01,  # userId
        0x03,  # funCode (response)
        0x20,  # sourceId
        0x00,  # pageIndex
        0x00, 0x00, 0x00,  # reserved
        0x00, 0x10,  # dataLength (16 bytes)
    ])
    
    example_payload = bytes([
        0x00, 0x01,  # segment count = 1
        0x00, 0x01,  # segment_id
        0x00, 0x01,  # segment_type
        0x00, 0x64,  # segment_address = 100
        0x00, 0x03,  # params_num = 3
        0x00, 0x32,  # value 1 = 50
        0xFF, 0xCE,  # value 2 = -50 (signed)
        0x00, 0x64,  # value 3 = 100
    ])
    
    example_message = example_header + example_payload
    
    # Parse
    result = parser.parse_message(example_message)
    if result:
        print("\nParsed values:")
        for key, value in result.all_values.items():
            print(f"  {key}: {value}")
    
    # Example: Build a command
    print("\n" + "=" * 50)
    print("Building command example:")
    
    builder = ESYCommandBuilder(user_id="12345678")
    command = builder.build_write_command(
        register_address=100,
        value=50
    )
    print(f"Command bytes: {command.hex()}")
    
    # Show topics
    print("\n" + "=" * 50)
    print("MQTT Topics for device 'ABC123':")
    topics = get_mqtt_topics("ABC123")
    for name, topic in topics.items():
        print(f"  {name}: {topic}")

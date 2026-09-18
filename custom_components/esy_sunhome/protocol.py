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
                _LOGGER.debug(
                    "Incomplete segment %d header: payload_bytes=%d, offset=%d, "
                    "available=%d, hex=%s",
                    i, len(payload), pos, len(payload) - pos, payload[:64].hex(),
                )
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
                _LOGGER.debug(
                    "Segment %d: not enough data (need %d, have %d); "
                    "payload_bytes=%d, seg_id=%d, seg_type=%d, seg_addr=%d, "
                    "params_num=%d, hex=%s",
                    i, values_len, len(payload) - pos, len(payload),
                    seg_id, seg_type, seg_addr, params_num, payload[:64].hex(),
                )
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

        # Phase type: 1 = single-phase, 3 = three-phase. Set from the config
        # entry by the coordinator; gates the 3-phase telemetry corrections in
        # _compute_derived_values (ported from the solaniq_optimizer ESY adapter).
        self.tp_type = 1

        # Key mappings for legacy compatibility.
        # Three-phase models expose grid/battery/load under different dataKeys
        # (the totalPowerOf*InFlow / total*Power keys). Alias them onto the
        # canonical keys the derive logic already consumes. NOTE:
        # totalPowerOfGridInFlow is handled explicitly in _compute_derived_values
        # because its sign convention differs (positive = import) from the
        # ESY energyFlowGridPower figure, so it is intentionally NOT aliased here.
        self._legacy_key_map = {
            "battTotalSoc": "batterySoc",
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
            # Three-phase aliases (battery in-flow + whole-site load totals).
            "totalPowerOfBatteryInFlow": "energyFlowBatt",
            "totalLoadActivePower": "loadRealTimePower",
            "totalHouseholdLoadPower": "loadActivePower",
        }

    def set_tp_type(self, tp_type: int) -> None:
        """Set the site phase type (1 = single-phase, 3 = three-phase)."""
        try:
            self.tp_type = 3 if int(tp_type) == 3 else 1
        except (TypeError, ValueError):
            self.tp_type = 1
        _LOGGER.info("Parser phase type set to %d-phase", self.tp_type)

    def set_protocol(self, protocol: ProtocolDefinition):
        """Set the protocol definition to use."""
        self.protocol = protocol
        _LOGGER.info("Protocol definition updated: %d input regs, %d holding regs",
                     len(protocol.input_registers), len(protocol.holding_registers))

    def parse_message(self, data: bytes) -> Optional[Dict[str, Any]]:
        """Parse binary telemetry message into dict."""
        if not data or len(data) < HEADER_SIZE:
            _LOGGER.debug("Message too short: %d bytes", len(data) if data else 0)
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

        if not segments:
            _LOGGER.debug("Ignoring message with 0 parsed segments (funCode=%d)", header.fun_code)
            return None

        # Build telemetry data
        result = self._build_telemetry_data(segments, header)
        if not any(not key.startswith("_") for key in result):
            _LOGGER.debug("No known telemetry registers in message")
            return None

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
        # None is not a measurement. Keep genuine zero values.
        values = {key: value for key, value in values.items() if value is not None}
        result = dict(values)

        # Only combine inputs present in this packet. A register absent from
        # the device's protocol is not an input; a defined but absent register
        # is missing telemetry and must not be treated as zero.
        pv_keys = ("pv1Power", "pv2Power", "ct2Power")
        if self.protocol:
            defined = {reg.data_key for reg in self.protocol.input_registers.values()}
            defined.update(reg.data_key for reg in self.protocol.holding_registers.values())
            pv_keys = tuple(key for key in pv_keys if key in defined or key in values)
        dc_keys = tuple(key for key in pv_keys if key != "ct2Power")
        if dc_keys and all(key in values for key in dc_keys):
            result["dcPvPower"] = sum(values[key] for key in dc_keys)
        if "ct2Power" in values:
            result["acPvPower"] = max(0, values["ct2Power"])
        if pv_keys and all(key in values for key in pv_keys):
            total = sum(values[key] for key in dc_keys) + max(0, values.get("ct2Power", 0))
            result["pvPower"] = total or values.get("energyFlowPvTotalPower", 0)
        elif "energyFlowPvTotalPower" in values:
            result["pvPower"] = values["energyFlowPvTotalPower"]
        if "pvPower" in result:
            result["pvLine"] = int(result["pvPower"] > 10)

        # Grid candidates are complete measurements, in HA sign convention
        # (+import). Preserve the existing significant-reading preference,
        # but fall back only to an observed reading, including a genuine zero.
        candidates = []
        if self.tp_type == 3:
            if "totalPowerOfGridInFlow" in values:
                candidates.append(round(values["totalPowerOfGridInFlow"]))
            if "totalgridActivePower" in values:
                candidates.append(-values["totalgridActivePower"])
            else:
                phases = ("phaseAgridActivePower", "phaseBgridActivePower", "phaseCgridActivePower")
                if all(key in values for key in phases):
                    candidates.append(-sum(values[key] for key in phases))
        elif "ct1Power" in values:
            candidates.append(-values["ct1Power"])
        for key in ("gridActivePower", "energyFlowGridPower", "energyFlowGrid"):
            if key in values:
                candidates.append(-values[key])
        # A positive CT2 measures AC solar, so cannot imply zero grid power.
        if self.tp_type == 1 and values.get("ct2Power", 0) < -10:
            candidates.append(-values["ct2Power"])
        if candidates:
            grid_power = next((power for power in candidates if abs(power) > 10), candidates[0])
            result["gridPower"] = grid_power
            result["gridImport"] = max(0, grid_power)
            result["gridExport"] = max(0, -grid_power)
            result["gridLine"] = int(grid_power != 0)

        # === BATTERY POWER ===
        # Standard convention: Positive = Charging, Negative = Discharging
        if any(k in values for k in ("energyFlowBattPower", "energyFlowBatt", "batteryPower")):
            raw_batt_power = (
                values.get("energyFlowBattPower") or
                values.get("energyFlowBatt") or
                values.get("batteryPower") or 0
            )

            result["batteryPower"] = abs(raw_batt_power)
            if "batteryStatus" in values:
                battery_status = values["batteryStatus"]

                # Status text mapping
                BATTERY_STATUS_TEXT = {
                    0: "Standby",
                    1: "Charging",
                    2: "Charge Topping",
                    3: "Float Charge",
                    4: "Full",
                    5: "Discharging",
                }

                # Determine charge/discharge based on status code
                if battery_status == 5:
                    # Discharging
                    is_charging = False
                    is_discharging = True
                    status_text = "Discharging"
                elif battery_status in (1, 2, 3, 6):
                    # Charging (various charging states)
                    is_charging = True
                    is_discharging = False
                    status_text = BATTERY_STATUS_TEXT.get(battery_status, "Charging")
                elif battery_status == 4:
                    # Full - not actively charging/discharging
                    is_charging = False
                    is_discharging = False
                    status_text = "Full"
                else:
                    # 0 or unknown - standby/idle
                    is_charging = False
                    is_discharging = False
                    status_text = "Standby"

                # Make battery power absolute since direction comes from status
                batt_power = abs(raw_batt_power)

                # If power is 0 but status says full, keep full status
                # If power is 0 and status is not 4 (full), show as standby
                if batt_power == 0 and battery_status != 4:
                    is_charging = False
                    is_discharging = False
                    status_text = "Standby"

                result["batteryPower"] = batt_power
                result["batteryStatus"] = battery_status

                # Directional battery power for HA sensors
                if is_discharging and batt_power > 0:
                    result["batteryImport"] = 0
                    result["batteryExport"] = batt_power  # Discharging = export (from battery)
                    result["batteryStatusText"] = status_text
                    result["batteryLine"] = 1
                elif is_charging and batt_power > 0:
                    result["batteryImport"] = batt_power  # Charging = import (into battery)
                    result["batteryExport"] = 0
                    result["batteryStatusText"] = status_text
                    result["batteryLine"] = 2
                else:
                    result["batteryImport"] = 0
                    result["batteryExport"] = 0
                    result["batteryStatusText"] = status_text
                    result["batteryLine"] = 0

                _LOGGER.debug("Battery: raw=%d, status=%d (%s), power=%d",
                             raw_batt_power, battery_status, status_text, batt_power)

        # === LOAD POWER ===
        if any(k in values for k in ("energyFlowLoadTotalPower", "energyFlowLoad", "loadRealTimePower", "loadActivePower", "loadPower")):
            load_power = (
                values.get("energyFlowLoadTotalPower") or
                values.get("energyFlowLoad") or
                values.get("loadRealTimePower") or
                values.get("loadActivePower") or
                values.get("loadPower") or 0
            )
            result["loadPower"] = load_power
            result["loadLine"] = 1 if load_power > 10 else 0

        # === 3-PHASE FLOW NORMALISATION (match ESY app EnergyFlowOptimize.i) ===
        # The 3-phase per-source registers are gross: pv + grid + battery
        # overshoot the (accurate) load by a residual, so PV/grid/battery read a
        # couple hundred watts high vs the app. The app forces conservation by
        # subtracting the residual EQUALLY from each active flow (pv, grid,
        # battery), leaving load fixed; we then dump any rounding leftover on the
        # largest flow so pv + grid + battery == load exactly. Signed convention
        # here: pv >= 0; grid +import/-export; batt +discharge/-charge.
        if self.tp_type == 3 and all(
            key in result for key in ("pvPower", "gridPower", "batteryImport", "batteryExport", "loadPower")
        ):
            pv = float(result.get("pvPower", 0) or 0)
            grid = float(result.get("gridPower", 0) or 0)
            batt = float(result.get("batteryExport", 0) or 0) - float(
                result.get("batteryImport", 0) or 0
            )
            load = float(result.get("loadPower", 0) or 0)
            cur = {"pv": pv, "grid": grid, "batt": batt}
            active = [k for k, v in cur.items() if abs(v) >= 1]
            residual = pv + grid + batt - load
            # Guard: only normalise when we actually have a load reading,
            # otherwise a missing load would zero out the source flows.
            if active and load >= 1 and abs(residual) >= 1:
                d = residual / len(active)
                for k in active:
                    nv = cur[k] - d
                    # Never flip a flow's sign (cap at zero).
                    if (cur[k] > 0) != (nv > 0) and nv != 0:
                        nv = 0.0
                    cur[k] = nv
                leftover = (cur["pv"] + cur["grid"] + cur["batt"]) - load
                big = max(active, key=lambda k: abs(cur[k]))
                cur[big] -= leftover

                result["pvPower"] = max(0, round(cur["pv"]))

                g = round(cur["grid"])
                result["gridPower"] = g
                if g > 0:
                    result["gridImport"], result["gridExport"], result["gridLine"] = g, 0, 1
                elif g < 0:
                    result["gridImport"], result["gridExport"], result["gridLine"] = 0, -g, 1
                else:
                    result["gridImport"], result["gridExport"], result["gridLine"] = 0, 0, 0

                b = round(cur["batt"])  # +discharge / -charge
                result["batteryPower"] = abs(b)
                if b > 0:
                    result["batteryImport"], result["batteryExport"], result["batteryLine"] = 0, b, 1
                elif b < 0:
                    result["batteryImport"], result["batteryExport"], result["batteryLine"] = -b, 0, 2
                else:
                    result["batteryImport"], result["batteryExport"], result["batteryLine"] = 0, 0, 0
                    if result.get("batteryStatus") != 4:
                        result["batteryStatusText"] = "Standby"

        # Aliases use presence, not truthiness: zero SOC/energy/temperature
        # is valid. Never manufacture missing numeric sensor values.
        aliases = {
            "batterySoc": ("battTotalSoc", "batterySoc"),
            "inverterTemp": ("invTemperature", "inverterTemp"),
            "dailyPowerGeneration": ("dailyEnergyGeneration", "dailyPowerGeneration"),
            "totalPowerGeneration": ("totalEnergyGeneration", "totalPowerGeneration"),
            "dailyConsumption": ("dailyPowerConsumption", "dailyConsumption"),
            "dailyGridExport": ("dailyGridConnectionPower", "dailyGridExport"),
            "dailyBattCharge": ("dailyBattChargeEnergy", "dailyBattCharge"),
            "dailyBattDischarge": ("dailyBattDischargeEnergy", "dailyBattDischarge"),
            "gridVoltage": ("gridVolt", "gridVoltage", "phaseAgridVoltage"),
            "gridFrequency": ("gridFreq", "gridFrequency", "phaseAgridFrequency"),
            "energyFlowPv": ("energyFlowPvTotalPower", "energyFlowPv"),
            "energyFlowBatt": ("energyFlowBattPower", "energyFlowBatt"),
            "energyFlowGrid": ("energyFlowGridPower", "energyFlowGrid"),
            "energyFlowLoad": ("energyFlowLoadTotalPower", "energyFlowLoad"),
        }
        for target, sources in aliases.items():
            for source in sources:
                if source in values:
                    result[target] = values[source]
                    break
        if "batterySoc" in result and not 0 <= result["batterySoc"] <= 100:
            del result["batterySoc"]

        # Run status is not operating mode. In particular, a status-only
        # packet must not reset the select to Regular Mode; mode 0 is valid.
        if "systemRunMode" in values:
            mode_names = {
                1: "Regular Mode",
                4: "Emergency Mode",
                3: "Electricity Sell Mode",
                5: "AC Charging Off Emergency Mode",
                0: "Battery Priority Mode",
                2: "Grid Priority Mode",
                6: "PV Mode",
                7: "Forced Off Grid Mode",
            }
            mode = values["systemRunMode"]
            result["patternMode"] = mode
            result["code"] = mode_names.get(mode, f"Unknown Mode ({mode})")
            result["_modeCode"] = mode
            result["_runningModeCode"] = mode

        if "ratedPower" in values:
            rated = values["ratedPower"]
            result["ratedPower"] = rated * 100 if 10 < rated < 200 else rated

        return result


class ESYCommandBuilder:
    """Builder for commands to send to inverter."""

    @staticmethod
    def build_write_command(
        register_address: int,
        value: int,
        user_id: bytes = None,
        msg_id: int = 0,
        config_id: int = 0,
    ) -> bytes:
        """Build a write command for a single register.
        
        Based on MQTT traffic analysis, write commands use:
        - user_id ending in FC 14 (confirmed from traffic analysis)
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
            user_id: 8-byte user ID (default: write command ID)
            msg_id: Message ID (use timestamp for uniqueness)
            config_id: Config ID from protocol (some inverters may require this)
            
        Returns:
            Binary command to publish to DOWN topic
        """
        if user_id is None:
            # FC 14 is used for single register writes (confirmed from traffic analysis)
            # FC 17 is used for polling
            user_id = bytes([0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFC, 0x14])
        
        # Payload: num_ops(2) + addr(2) + count(2) + value(2)
        payload = struct.pack(">HHHH", 
            1,                  # 1 operation
            register_address,   # address
            1,                  # 1 value
            value               # the value
        )
        
        header = MsgHeader(
            config_id=config_id,
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
        config_id: int = 0,
    ) -> bytes:
        """Build a write command for multiple registers.
        
        Args:
            writes: List of (address, [values]) tuples
            user_id: 8-byte user ID (default: write command ID)
            msg_id: Message ID
            config_id: Config ID from protocol (some inverters may require this)
            
        Returns:
            Binary command to publish to DOWN topic
        """
        if user_id is None:
            # FC 17 is used for multi-register writes (confirmed from traffic analysis)
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
            config_id=config_id,
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

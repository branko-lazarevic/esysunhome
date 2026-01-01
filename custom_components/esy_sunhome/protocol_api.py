"""
ESY Sunhome Protocol API - Dynamic Register Loading

Fetches register definitions from the ESY API to ensure correct mappings
for all device models and firmware versions.
"""

import logging
import aiohttp
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .const import (
    ESY_API_BASE_URL,
    ESY_API_PROTOCOL_LIST,
    ESY_API_PROTOCOL_SEGMENT,
    DEFAULT_PV_POWER,
    DEFAULT_TP_TYPE,
    DEFAULT_MCU_VERSION,
    DATA_TYPE_SIGNED,
    DATA_TYPE_UNSIGNED,
    FC_READ_INPUT,
    FC_READ_HOLDING,
)

_LOGGER = logging.getLogger(__name__)

# Cache duration for protocol definitions (24 hours)
PROTOCOL_CACHE_DURATION = timedelta(hours=24)


@dataclass
class RegisterDefinition:
    """Definition of a single Modbus register."""
    address: int
    data_key: str
    data_type: str  # "signed" or "unsigned"
    coefficient: float
    unit: str
    data_length: int  # 2 for 16-bit, 4 for 32-bit
    function_code: int  # 3 = Holding, 4 = Input
    can_show: bool = True
    can_set: bool = False
    
    @property
    def is_32bit(self) -> bool:
        return self.data_length == 4


@dataclass
class SegmentDefinition:
    """Definition of a polling segment."""
    segment_id: int
    function_code: int
    start_address: int
    param_count: int
    fast_upload: bool = False
    
    @property
    def end_address(self) -> int:
        return self.start_address + self.param_count - 1


@dataclass
class ProtocolDefinition:
    """Complete protocol definition for a device."""
    config_id: int
    pv_power: int
    tp_type: int
    mcu_version: int
    input_registers: Dict[int, RegisterDefinition] = field(default_factory=dict)
    holding_registers: Dict[int, RegisterDefinition] = field(default_factory=dict)
    segments: List[SegmentDefinition] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=datetime.utcnow)
    
    def get_register(self, address: int, function_code: int = FC_READ_INPUT) -> Optional[RegisterDefinition]:
        """Get register definition by address and function code."""
        if function_code == FC_READ_INPUT:
            return self.input_registers.get(address)
        elif function_code == FC_READ_HOLDING:
            return self.holding_registers.get(address)
        return None
    
    def is_expired(self) -> bool:
        """Check if the cached protocol is expired."""
        return datetime.utcnow() - self.fetched_at > PROTOCOL_CACHE_DURATION


class ProtocolAPI:
    """API client for fetching protocol definitions."""
    
    def __init__(self, access_token: str):
        self.access_token = access_token
        self._session: Optional[aiohttp.ClientSession] = None
        self._protocol_cache: Dict[str, ProtocolDefinition] = {}
    
    def _cache_key(self, pv_power: int, tp_type: int, mcu_version: int) -> str:
        """Generate cache key for protocol definition."""
        return f"{pv_power}_{tp_type}_{mcu_version}"
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    def update_token(self, access_token: str):
        """Update the access token."""
        self.access_token = access_token
    
    async def fetch_protocol_list(
        self,
        pv_power: int = DEFAULT_PV_POWER,
        tp_type: int = DEFAULT_TP_TYPE,
        mcu_version: int = DEFAULT_MCU_VERSION,
    ) -> Optional[Dict[str, Any]]:
        """Fetch protocol register list from API."""
        url = f"{ESY_API_BASE_URL}{ESY_API_PROTOCOL_LIST}"
        params = {
            "pvPower": pv_power,
            "tpType": tp_type,
            "mcuVersion": mcu_version,
        }
        headers = {"Authorization": f"bearer {self.access_token}"}
        
        try:
            session = await self._get_session()
            async with session.get(url, params=params, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("code") == 0:
                        _LOGGER.info("Successfully fetched protocol list from API")
                        return data.get("data", {})
                    else:
                        _LOGGER.error("API error: %s", data.get("msg"))
                else:
                    _LOGGER.error("Failed to fetch protocol list: HTTP %d", response.status)
        except Exception as e:
            _LOGGER.error("Exception fetching protocol list: %s", e)
        
        return None
    
    async def fetch_protocol_segments(
        self,
        pv_power: int = DEFAULT_PV_POWER,
        tp_type: int = DEFAULT_TP_TYPE,
        mcu_version: int = DEFAULT_MCU_VERSION,
    ) -> Optional[Dict[str, Any]]:
        """Fetch protocol segment definitions from API."""
        url = f"{ESY_API_BASE_URL}{ESY_API_PROTOCOL_SEGMENT}"
        params = {
            "pvPower": pv_power,
            "tpType": tp_type,
            "mcuVersion": mcu_version,
        }
        headers = {"Authorization": f"bearer {self.access_token}"}
        
        try:
            session = await self._get_session()
            async with session.get(url, params=params, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("code") == 0:
                        _LOGGER.info("Successfully fetched protocol segments from API")
                        return data.get("data", {})
                    else:
                        _LOGGER.error("API error: %s", data.get("msg"))
                else:
                    _LOGGER.error("Failed to fetch protocol segments: HTTP %d", response.status)
        except Exception as e:
            _LOGGER.error("Exception fetching protocol segments: %s", e)
        
        return None
    
    def _parse_register(self, reg_data: dict, function_code: int) -> Optional[RegisterDefinition]:
        """Parse a single register definition from API response."""
        try:
            addresses = reg_data.get("address", [])
            if not addresses:
                return None
            
            # Get primary address (first in list)
            primary_addr = addresses[0].get("dec", 0)
            
            # Parse coefficient - handle string or number
            coeff = reg_data.get("coefficient", "1")
            if isinstance(coeff, str):
                coeff = float(coeff) if coeff else 1.0
            else:
                coeff = float(coeff)
            
            return RegisterDefinition(
                address=primary_addr,
                data_key=reg_data.get("dataKey", f"unknown_{primary_addr}"),
                data_type=reg_data.get("dataType", DATA_TYPE_UNSIGNED),
                coefficient=coeff,
                unit=reg_data.get("unit", ""),
                data_length=reg_data.get("dataLength", 2),
                function_code=function_code,
                can_show=reg_data.get("canShow", True),
                can_set=reg_data.get("canSet", False) or reg_data.get("installerSet", False),
            )
        except Exception as e:
            _LOGGER.warning("Failed to parse register: %s", e)
            return None
    
    def _parse_segment(self, seg_data: dict) -> Optional[SegmentDefinition]:
        """Parse a segment definition from API response."""
        try:
            return SegmentDefinition(
                segment_id=seg_data.get("segmentId", 0),
                function_code=seg_data.get("functionCode", FC_READ_INPUT),
                start_address=seg_data.get("startAddress", 0),
                param_count=seg_data.get("paramNum", 0),
                fast_upload=seg_data.get("fastUp", 0) == 1,
            )
        except Exception as e:
            _LOGGER.warning("Failed to parse segment: %s", e)
            return None
    
    async def get_protocol_definition(
        self,
        pv_power: int = DEFAULT_PV_POWER,
        tp_type: int = DEFAULT_TP_TYPE,
        mcu_version: int = DEFAULT_MCU_VERSION,
        force_refresh: bool = False,
    ) -> Optional[ProtocolDefinition]:
        """Get complete protocol definition, using cache if available."""
        cache_key = self._cache_key(pv_power, tp_type, mcu_version)
        
        # Check cache
        if not force_refresh and cache_key in self._protocol_cache:
            cached = self._protocol_cache[cache_key]
            if not cached.is_expired():
                _LOGGER.debug("Using cached protocol definition")
                return cached
        
        # Fetch from API
        _LOGGER.info("Fetching protocol definition for pvPower=%d, tpType=%d, mcuVersion=%d",
                     pv_power, tp_type, mcu_version)
        
        protocol_list = await self.fetch_protocol_list(pv_power, tp_type, mcu_version)
        segment_list = await self.fetch_protocol_segments(pv_power, tp_type, mcu_version)
        
        if not protocol_list:
            _LOGGER.warning("Failed to fetch protocol list, using fallback")
            return self._get_fallback_protocol()
        
        # Parse protocol definition
        protocol = ProtocolDefinition(
            config_id=segment_list.get("configId", 0) if segment_list else 0,
            pv_power=pv_power,
            tp_type=tp_type,
            mcu_version=mcu_version,
        )
        
        # Parse input registers (Function Code 4)
        input_regs = protocol_list.get("readInputRegister", [])
        for reg_data in input_regs:
            reg = self._parse_register(reg_data, FC_READ_INPUT)
            if reg:
                protocol.input_registers[reg.address] = reg
        
        _LOGGER.info("Loaded %d input registers", len(protocol.input_registers))
        
        # Parse holding registers (Function Code 3)
        holding_regs = protocol_list.get("readHoldRegister", [])
        for reg_data in holding_regs:
            reg = self._parse_register(reg_data, FC_READ_HOLDING)
            if reg:
                protocol.holding_registers[reg.address] = reg
        
        _LOGGER.info("Loaded %d holding registers", len(protocol.holding_registers))
        
        # Parse segments
        if segment_list:
            segments = segment_list.get("segments", [])
            for seg_data in segments:
                seg = self._parse_segment(seg_data)
                if seg:
                    protocol.segments.append(seg)
            
            _LOGGER.info("Loaded %d segments", len(protocol.segments))
        
        # Cache the result
        self._protocol_cache[cache_key] = protocol
        
        return protocol
    
    def _get_fallback_protocol(self) -> ProtocolDefinition:
        """Get fallback protocol definition when API is unavailable."""
        _LOGGER.warning("Using fallback protocol definition")
        
        protocol = ProtocolDefinition(
            config_id=6,
            pv_power=DEFAULT_PV_POWER,
            tp_type=DEFAULT_TP_TYPE,
            mcu_version=DEFAULT_MCU_VERSION,
        )
        
        # Add essential registers based on known good mappings
        fallback_input_regs = [
            (5, "systemRunMode", DATA_TYPE_UNSIGNED, 1, ""),
            # Register 6: Previously thought to be systemRunStatus, but MQTT data shows
            # it contains the pattern/schedule mode (e.g., 5=BEM) while register 5 shows
            # the current running mode. Capture as both names for compatibility.
            (6, "patternMode", DATA_TYPE_UNSIGNED, 1, ""),  # Schedule mode setting
            (7, "dcdcTemperature", DATA_TYPE_SIGNED, 0.1, "℃"),
            (10, "dailyEnergyGeneration", DATA_TYPE_UNSIGNED, 0.001, "kWh"),
            (12, "totalEnergyGeneration", DATA_TYPE_UNSIGNED, 0.001, "kWh"),
            (14, "ratedPower", DATA_TYPE_SIGNED, 100, "W"),
            (20, "pv1voltage", DATA_TYPE_SIGNED, 0.1, "V"),
            (21, "pv1current", DATA_TYPE_SIGNED, 0.1, "A"),
            (22, "pv1Power", DATA_TYPE_SIGNED, 1, "W"),
            (23, "pv2voltage", DATA_TYPE_SIGNED, 0.1, "V"),
            (24, "pv2current", DATA_TYPE_SIGNED, 0.1, "A"),
            (25, "pv2Power", DATA_TYPE_SIGNED, 1, "W"),
            (28, "batteryStatus", DATA_TYPE_UNSIGNED, 1, ""),
            (29, "batteryVoltage", DATA_TYPE_SIGNED, 0.1, "V"),
            (30, "batteryCurrent", DATA_TYPE_SIGNED, 0.1, "A"),
            (31, "batteryPower", DATA_TYPE_SIGNED, 1, "W"),
            (32, "battTotalSoc", DATA_TYPE_SIGNED, 1, "%"),
            (39, "gridFreq", DATA_TYPE_SIGNED, 0.01, "Hz"),
            (42, "gridVolt", DATA_TYPE_SIGNED, 0.1, "V"),
            (46, "gridActivePower", DATA_TYPE_SIGNED, 1, "W"),
            (49, "ct1Power", DATA_TYPE_SIGNED, 1, "W"),
            (52, "invTemperature", DATA_TYPE_SIGNED, 0.1, "℃"),
            (56, "ct2Power", DATA_TYPE_SIGNED, 1, "W"),
            (71, "energyFlowPvTotalPower", DATA_TYPE_SIGNED, 10, "W"),
            (72, "energyFlowBattPower", DATA_TYPE_SIGNED, 10, "W"),
            (73, "energyFlowGridPower", DATA_TYPE_SIGNED, 10, "W"),
            (74, "energyFlowLoadTotalPower", DATA_TYPE_SIGNED, 10, "W"),
            (84, "loadActivePower", DATA_TYPE_SIGNED, 1, "W"),
            (90, "loadRealTimePower", DATA_TYPE_SIGNED, 1, "W"),
            (104, "meterPower", DATA_TYPE_SIGNED, 1, "W"),
            (126, "dailyPowerConsumption", DATA_TYPE_UNSIGNED, 0.001, "kWh"),
            (128, "dailyGridConnectionPower", DATA_TYPE_UNSIGNED, 0.001, "kWh"),
            (136, "dailyBattChargeEnergy", DATA_TYPE_UNSIGNED, 0.001, "kWh"),
            (140, "dailyBattDischargeEnergy", DATA_TYPE_UNSIGNED, 0.001, "kWh"),
            (290, "batterySoc", DATA_TYPE_UNSIGNED, 1, "%"),
            (291, "batterySoh", DATA_TYPE_UNSIGNED, 1, "%"),
        ]
        
        for addr, key, dtype, coeff, unit in fallback_input_regs:
            protocol.input_registers[addr] = RegisterDefinition(
                address=addr,
                data_key=key,
                data_type=dtype,
                coefficient=coeff,
                unit=unit,
                data_length=2,
                function_code=FC_READ_INPUT,
            )
        
        # Add essential holding registers (FC3) for settings
        fallback_holding_regs = [
            (57, "patternMode", DATA_TYPE_UNSIGNED, 1, ""),  # Schedule/pattern mode setting
            (196, "runModeSet0h", DATA_TYPE_UNSIGNED, 1, ""),  # Schedule hour 0
            (197, "runModeSet1h", DATA_TYPE_UNSIGNED, 1, ""),  # Schedule hour 1
            # ... hours 2-22 ...
            (219, "runModeSet23h", DATA_TYPE_UNSIGNED, 1, ""),  # Schedule hour 23
        ]
        
        for addr, key, dtype, coeff, unit in fallback_holding_regs:
            protocol.holding_registers[addr] = RegisterDefinition(
                address=addr,
                data_key=key,
                data_type=dtype,
                coefficient=coeff,
                unit=unit,
                data_length=2,
                function_code=FC_READ_HOLDING,
            )
        
        return protocol


# Singleton instance for caching
_protocol_api_instance: Optional[ProtocolAPI] = None


def get_protocol_api(access_token: str) -> ProtocolAPI:
    """Get or create the protocol API instance."""
    global _protocol_api_instance
    
    if _protocol_api_instance is None:
        _protocol_api_instance = ProtocolAPI(access_token)
    else:
        _protocol_api_instance.update_token(access_token)
    
    return _protocol_api_instance

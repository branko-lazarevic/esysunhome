"""Config flow for ESY Sunhome integration."""

import logging
import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .esysunhome import ESYSunhomeAPI
from .const import (
    DOMAIN,
    CONF_ENABLE_POLLING,
    CONF_DEVICE_SN,
    CONF_PV_POWER,
    CONF_TP_TYPE,
    CONF_MCU_VERSION,
    DEFAULT_ENABLE_POLLING,
    DEFAULT_PV_POWER,
    DEFAULT_TP_TYPE,
    DEFAULT_MCU_VERSION,
    ESY_API_BASE_URL,
    ESY_API_DEVICE_ENDPOINT,
)

_LOGGER = logging.getLogger(__name__)


async def fetch_devices(username: str, password: str) -> list:
    """Fetch available devices/inverters with detailed info."""
    api = ESYSunhomeAPI(username, password, "")
    try:
        await api.get_bearer_token()
        
        # Fetch device list with more details
        url = f"{ESY_API_BASE_URL}{ESY_API_DEVICE_ENDPOINT}"
        headers = {"Authorization": f"bearer {api.access_token}"}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    devices = data.get("data", {}).get("records", [])
                    _LOGGER.debug("Found %d devices", len(devices))
                    return devices
                else:
                    raise Exception(f"Failed to fetch devices: HTTP {response.status}")
    finally:
        await api.close_session()


async def fetch_device_details(api: ESYSunhomeAPI, device_id: str) -> dict:
    """Fetch detailed device information including protocol parameters."""
    url = f"{ESY_API_BASE_URL}/api/lsydevice/detail?deviceId={device_id}"
    headers = {"Authorization": f"bearer {api.access_token}"}
    
    session = None
    try:
        session = aiohttp.ClientSession()
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                return data.get("data", {})
    except Exception as e:
        _LOGGER.warning("Failed to fetch device details: %s", e)
    finally:
        if session:
            await session.close()
    
    return {}


def extract_protocol_params(device: dict) -> tuple:
    """Extract protocol parameters from device data."""
    # Try to find pvPower, tpType, mcuVersion in device data
    pv_power = device.get("pvPower") or device.get("pv_power") or DEFAULT_PV_POWER
    tp_type = device.get("tpType") or device.get("tp_type") or device.get("deviceType") or DEFAULT_TP_TYPE
    mcu_version = device.get("mcuVersion") or device.get("mcu_version") or device.get("mcuSoftwareVer") or DEFAULT_MCU_VERSION
    
    # Handle string values
    if isinstance(pv_power, str):
        pv_power = int(pv_power) if pv_power.isdigit() else DEFAULT_PV_POWER
    if isinstance(tp_type, str):
        tp_type = int(tp_type) if tp_type.isdigit() else DEFAULT_TP_TYPE
    if isinstance(mcu_version, str):
        mcu_version = int(mcu_version) if mcu_version.isdigit() else DEFAULT_MCU_VERSION
    
    return pv_power, tp_type, mcu_version


class ESYSunhomeFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ESY Sunhome."""

    VERSION = 2  # Increment version for new schema

    def __init__(self) -> None:
        """Initialize the flow handler."""
        self.username = None
        self.password = None
        self.device_id = None
        self.device_sn = None
        self.pv_power = DEFAULT_PV_POWER
        self.tp_type = DEFAULT_TP_TYPE
        self.mcu_version = DEFAULT_MCU_VERSION
        self.api = None
        self.devices = []

    async def async_step_user(self, user_input=None):
        """Handle the initial step for capturing credentials."""
        if user_input is not None:
            self.username = user_input["username"]
            self.password = user_input["password"]

            try:
                self.api = ESYSunhomeAPI(self.username, self.password, "")
                await self.api.get_bearer_token()
                
                self.devices = await fetch_devices(self.username, self.password)
                
                if not self.devices:
                    _LOGGER.error("No devices found for this account")
                    return self.async_show_form(
                        step_id="user",
                        data_schema=self._create_login_schema(),
                        errors={"base": "no_devices"},
                    )
                
                # Auto-select if only one device
                if len(self.devices) == 1:
                    device = self.devices[0]
                    self.device_id = str(device.get("id", ""))
                    self.device_sn = device.get("sn") or device.get("serialNumber") or self.device_id
                    
                    # Extract protocol parameters
                    self.pv_power, self.tp_type, self.mcu_version = extract_protocol_params(device)
                    
                    # Try to get more details
                    details = await fetch_device_details(self.api, self.device_id)
                    if details:
                        pv, tp, mcu = extract_protocol_params(details)
                        self.pv_power = pv or self.pv_power
                        self.tp_type = tp or self.tp_type
                        self.mcu_version = mcu or self.mcu_version
                    
                    _LOGGER.info("Auto-selected device: id=%s, sn=%s, pvPower=%d, tpType=%d, mcuVersion=%d",
                                self.device_id, self.device_sn, self.pv_power, self.tp_type, self.mcu_version)
                    
                    return await self.async_step_protocol()
                
                return await self.async_step_device_id()
                
            except Exception as err:
                _LOGGER.error("Failed to authenticate: %s", err)
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._create_login_schema(),
                    errors={"base": "auth_failed"},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self._create_login_schema(),
            errors=None,
        )

    def _create_login_schema(self):
        """Create the login schema."""
        return vol.Schema({
            vol.Required("username"): cv.string,
            vol.Required("password"): cv.string,
        })

    async def async_step_device_id(self, user_input=None):
        """Handle device selection."""
        if user_input is not None:
            self.device_id = user_input.get("device_id")
            
            # Find the selected device
            for device in self.devices:
                if str(device.get("id", "")) == self.device_id:
                    self.device_sn = device.get("sn") or device.get("serialNumber") or self.device_id
                    self.pv_power, self.tp_type, self.mcu_version = extract_protocol_params(device)
                    break
            
            # Try to get more details
            details = await fetch_device_details(self.api, self.device_id)
            if details:
                pv, tp, mcu = extract_protocol_params(details)
                self.pv_power = pv or self.pv_power
                self.tp_type = tp or self.tp_type
                self.mcu_version = mcu or self.mcu_version
            
            _LOGGER.info("Selected device: id=%s, sn=%s", self.device_id, self.device_sn)
            return await self.async_step_protocol()

        # Build device options
        device_options = {}
        for device in self.devices:
            device_id = str(device.get("id", ""))
            device_name = device.get("name", "Unknown")
            device_sn = device.get("sn") or device.get("serialNumber") or ""
            device_options[device_id] = f"{device_name} ({device_sn or device_id})"

        return self.async_show_form(
            step_id="device_id",
            data_schema=vol.Schema({
                vol.Required("device_id"): vol.In(device_options),
            }),
        )

    async def async_step_protocol(self, user_input=None):
        """Handle protocol parameter configuration."""
        if user_input is not None:
            self.pv_power = int(user_input.get("pv_power", self.pv_power))
            self.tp_type = int(user_input.get("tp_type", self.tp_type))
            self.mcu_version = int(user_input.get("mcu_version", self.mcu_version))
            return self._create_entry()

        return self.async_show_form(
            step_id="protocol",
            data_schema=vol.Schema({
                vol.Required("pv_power", default=str(self.pv_power)): cv.string,
                vol.Required("tp_type", default=str(self.tp_type)): cv.string,
                vol.Required("mcu_version", default=str(self.mcu_version)): cv.string,
            }),
            description_placeholders={
                "pv_power": str(self.pv_power),
                "tp_type": str(self.tp_type),
                "mcu_version": str(self.mcu_version),
            },
        )

    def _create_entry(self):
        """Create the config entry."""
        return self.async_create_entry(
            title=f"ESY Sunhome ({self.device_sn or self.device_id})",
            data={
                "username": self.username,
                "password": self.password,
                "device_id": self.device_id,
                CONF_DEVICE_SN: self.device_sn,
                CONF_PV_POWER: self.pv_power,
                CONF_TP_TYPE: self.tp_type,
                CONF_MCU_VERSION: self.mcu_version,
            },
            options={
                CONF_ENABLE_POLLING: DEFAULT_ENABLE_POLLING,
            },
        )

    async def async_step_import(self, user_input=None):
        """Handle importing configuration."""
        return await self.async_step_user(user_input)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow."""

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_ENABLE_POLLING,
                    default=self.config_entry.options.get(
                        CONF_ENABLE_POLLING, DEFAULT_ENABLE_POLLING
                    ),
                ): bool,
            }),
        )

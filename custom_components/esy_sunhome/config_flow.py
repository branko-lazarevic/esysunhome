import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from .esysunhome import ESYSunhomeAPI
from .const import (
    CONF_ENABLE_POLLING,
    CONF_DEVICE_SN,
    DEFAULT_ENABLE_POLLING,
    ESY_API_BASE_URL,
    ESY_API_DEVICE_ENDPOINT,
)

_LOGGER = logging.getLogger(__name__)


async def fetch_devices(username: str, password: str):
    """Fetch available devices/inverters."""
    api = ESYSunhomeAPI(username, password, "")
    await api.get_bearer_token()
    url = f"{ESY_API_BASE_URL}{ESY_API_DEVICE_ENDPOINT}"
    headers = {"Authorization": f"bearer {api.access_token}"}
    
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                devices = data.get("data", {}).get("records", [])
                return devices
            else:
                raise Exception(f"Failed to fetch devices. Status: {response.status}")


class ESYSunhomeFlowHandler(config_entries.ConfigFlow, domain="esy_sunhome"):
    """Handle a config flow for the ESY Sunhome integration."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow handler."""
        self.username = None
        self.password = None
        self.device_id = None
        self.device_sn = None
        self.api = None
        self.devices = []

    async def async_step_user(self, user_input=None):
        """Handle the first step for capturing username and password."""
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
                        data_schema=self.create_schema(),
                        errors={"base": "no_devices"},
                    )
                
                if len(self.devices) == 1:
                    device = self.devices[0]
                    self.device_id = str(device["id"])
                    # Get serial number for MQTT topic
                    self.device_sn = device.get("sn") or device.get("serialNumber") or self.device_id
                    _LOGGER.info("Auto-selected device: id=%s, sn=%s", self.device_id, self.device_sn)
                    return self._create_entry()
                
                return await self.async_step_device_id()
                
            except Exception as err:
                _LOGGER.error("Failed to authenticate: %s", err)
                return self.async_show_form(
                    step_id="user",
                    data_schema=self.create_schema(),
                    errors={"base": "auth_failed"},
                )

        return self.async_show_form(
            step_id="user", data_schema=self.create_schema(), errors=None
        )

    def create_schema(self):
        """Create the schema for user input."""
        return vol.Schema(
            {
                vol.Required("username"): cv.string,
                vol.Required("password"): cv.string,
            }
        )

    async def async_step_device_id(self, user_input=None):
        """Handle the step to select device ID from available devices."""
        if user_input is not None:
            self.device_id = user_input.get("device_id")
            # Find the selected device and get its SN
            for device in self.devices:
                if str(device.get("id", "")) == self.device_id:
                    self.device_sn = device.get("sn") or device.get("serialNumber") or self.device_id
                    break
            _LOGGER.info("Selected device: id=%s, sn=%s", self.device_id, self.device_sn)
            return self._create_entry()

        device_options = {}
        for device in self.devices:
            device_id = str(device.get("id", ""))
            device_name = device.get("name", "Unknown")
            device_sn = device.get("sn") or device.get("serialNumber") or ""
            device_options[device_id] = f"{device_name} ({device_sn or device_id})"

        return self.async_show_form(
            step_id="device_id",
            data_schema=vol.Schema(
                {
                    vol.Required("device_id"): vol.In(device_options),
                }
            ),
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
        """Get the options flow for this handler."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for ESY Sunhome."""

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ENABLE_POLLING,
                        default=self.config_entry.options.get(
                            CONF_ENABLE_POLLING, DEFAULT_ENABLE_POLLING
                        ),
                    ): bool,
                }
            ),
        )

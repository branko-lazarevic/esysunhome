"""Config flow for ESY Sunhome integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .esysunhome import ESYSunhomeAPI
from .const import (
    DOMAIN,
    CONF_ENABLE_POLLING,
    CONF_USER_ID,
    CONF_DEVICE_SN,
    DEFAULT_ENABLE_POLLING,
    ESY_API_BASE_URL,
    ESY_API_DEVICE_ENDPOINT,
)

_LOGGER = logging.getLogger(__name__)


async def fetch_devices(username: str, password: str) -> tuple[list, str | None, dict]:
    """Fetch available devices/inverters and user ID.

    Returns:
        Tuple of (devices list, user_id or None, device_sn_map)
    """
    api = ESYSunhomeAPI(username, password, "")
    try:
        await api.get_bearer_token()

        # Fetch device info using the device endpoint
        url = f"{ESY_API_BASE_URL}{ESY_API_DEVICE_ENDPOINT}"
        headers = {"Authorization": f"bearer {api.access_token}"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    _LOGGER.debug("Device API response: %s", data)
                    devices = data.get("data", {}).get("records", [])

                    # Try to extract user_id from device data
                    user_id = None
                    device_sn_map = {}  # Maps device_id -> deviceSn
                    
                    if devices and len(devices) > 0:
                        first_device = devices[0]
                        # Try multiple possible field names for user ID
                        user_id = first_device.get("userId") or first_device.get("user_id") or first_device.get("createBy")
                        if user_id:
                            user_id = str(user_id)
                        _LOGGER.debug("Extracted user_id: %s from device: %s", user_id, first_device.get("id"))
                        
                        # Build device_id -> deviceSn mapping
                        for device in devices:
                            dev_id = str(device.get("id", ""))
                            dev_sn = device.get("deviceSn") or device.get("sn") or device.get("serialNumber")
                            if dev_id and dev_sn:
                                device_sn_map[dev_id] = dev_sn
                                _LOGGER.debug("Device %s has serial number: %s", dev_id, dev_sn)

                    return devices, user_id, device_sn_map
                else:
                    raise Exception(f"Failed to fetch devices. Status: {response.status}")
    finally:
        # Always close the API session
        await api.close_session()


class ESYSunhomeFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the ESY Sunhome integration."""

    VERSION = 3  # Bumped version for device_sn support

    def __init__(self) -> None:
        """Initialize the flow handler."""
        self.username: str | None = None
        self.password: str | None = None
        self.device_id: str | None = None
        self.device_sn: str | None = None  # Serial number for MQTT topics
        self.user_id: str | None = None
        self.api: ESYSunhomeAPI | None = None
        self.devices: list = []
        self.device_sn_map: dict = {}  # Maps device_id -> deviceSn

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the first step for capturing username and password."""
        if user_input is not None:
            self.username = user_input["username"]
            self.password = user_input["password"]

            # Check credentials by initializing the API and trying to authenticate
            try:
                # Fetch available devices and user_id (this validates credentials too)
                self.devices, self.user_id, self.device_sn_map = await fetch_devices(
                    self.username, self.password
                )

                if not self.devices:
                    _LOGGER.error("No devices found for this account")
                    return self.async_show_form(
                        step_id="user",
                        data_schema=self._create_schema(),
                        errors={"base": "no_devices"},
                    )

                # If only one device, auto-select it
                if len(self.devices) == 1:
                    self.device_id = str(self.devices[0]["id"])
                    self.device_sn = self.device_sn_map.get(self.device_id)
                    return self._create_entry()

                # Multiple devices, show selection
                return await self.async_step_device_id()

            except Exception as err:
                _LOGGER.error(
                    "Failed to authenticate with the provided username/password: %s",
                    err,
                )
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._create_schema(),
                    errors={"base": "auth_failed"},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self._create_schema(),
            errors=None,
        )

    def _create_schema(self) -> vol.Schema:
        """Create the schema for user input."""
        return vol.Schema(
            {
                vol.Required("username"): cv.string,
                vol.Required("password"): cv.string,
            }
        )

    async def async_step_device_id(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the step to select device ID from available devices."""
        if user_input is not None:
            self.device_id = user_input.get("device_id")
            self.device_sn = self.device_sn_map.get(self.device_id)
            return self._create_entry()

        # Create device selection options
        device_options = {}
        for device in self.devices:
            device_id = str(device.get("id", ""))
            device_name = device.get("name", "Unknown")
            device_sn = device.get("deviceSn", "")
            # Show serial number in the selection if available
            if device_sn:
                device_options[device_id] = f"{device_name} ({device_sn})"
            else:
                device_options[device_id] = f"{device_name} ({device_id})"

        # Show device selection form
        return self.async_show_form(
            step_id="device_id",
            data_schema=vol.Schema(
                {
                    vol.Required("device_id"): vol.In(device_options),
                }
            ),
        )

    def _create_entry(self) -> config_entries.ConfigFlowResult:
        """Create the config entry."""
        # Use serial number in title if available
        title = f"ESY Sunhome ({self.device_sn or self.device_id})"
        
        return self.async_create_entry(
            title=title,
            data={
                "username": self.username,
                "password": self.password,
                "device_id": self.device_id,
                CONF_DEVICE_SN: self.device_sn,  # Serial number for MQTT topics
                CONF_USER_ID: self.user_id,
            },
            options={
                CONF_ENABLE_POLLING: DEFAULT_ENABLE_POLLING,
            },
        )

    async def async_step_import(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle importing configuration."""
        return await self.async_step_user(user_input)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for ESY Sunhome."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
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

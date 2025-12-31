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
    DEFAULT_ENABLE_POLLING,
    ESY_API_BASE_URL,
    ESY_API_DEVICE_ENDPOINT,
)

_LOGGER = logging.getLogger(__name__)


async def fetch_devices(username: str, password: str) -> tuple[list, str | None]:
    """Fetch available devices/inverters and user ID.

    Returns:
        Tuple of (devices list, user_id or None)
    """
    api = ESYSunhomeAPI(username, password, "")
    await api.get_bearer_token()

    # Try to extract user_id from the login response
    user_id = None

    # Fetch device info using the device endpoint
    url = f"{ESY_API_BASE_URL}{ESY_API_DEVICE_ENDPOINT}"
    headers = {"Authorization": f"bearer {api.access_token}"}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                devices = data.get("data", {}).get("records", [])

                # Try to extract user_id from device data if available
                if devices and len(devices) > 0:
                    # The user_id might be in the device record or we use the device's
                    # associated user info
                    first_device = devices[0]
                    user_id = str(first_device.get("userId", ""))

                return devices, user_id
            else:
                raise Exception(f"Failed to fetch devices. Status: {response.status}")


class ESYSunhomeFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the ESY Sunhome integration."""

    VERSION = 2  # Bumped version for v2.0.0

    def __init__(self) -> None:
        """Initialize the flow handler."""
        self.username: str | None = None
        self.password: str | None = None
        self.device_id: str | None = None
        self.user_id: str | None = None
        self.api: ESYSunhomeAPI | None = None
        self.devices: list = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the first step for capturing username and password."""
        if user_input is not None:
            self.username = user_input["username"]
            self.password = user_input["password"]

            # Check credentials by initializing the API and trying to authenticate
            try:
                self.api = ESYSunhomeAPI(self.username, self.password, "")
                await self.api.get_bearer_token()

                # Automatically fetch available devices and user_id
                self.devices, self.user_id = await fetch_devices(
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
            return self._create_entry()

        # Create device selection options
        device_options = {}
        for device in self.devices:
            device_id = str(device.get("id", ""))
            device_name = device.get("name", "Unknown")
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
        return self.async_create_entry(
            title=f"ESY Sunhome ({self.device_id})",
            data={
                "username": self.username,
                "password": self.password,
                "device_id": self.device_id,
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

import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import config_validation as cv
from .esysunhome import ESYSunhomeAPI

_LOGGER = logging.getLogger(__name__)


class ESYSunhomeFlowHandler(config_entries.ConfigFlow, domain="esy_sunhome"):
    """Handle a config flow for the ESY Sunhome integration."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow handler."""
        self.username = None
        self.password = None
        self.device_id = None
        self.api = None

    async def async_step_user(self, user_input=None):
        """Handle the first step for capturing username and password."""
        if user_input is not None:
            self.username = user_input["username"]
            self.password = user_input["password"]

            # Check credentials by initializing the API and trying to authenticate
            try:
                self.api = ESYSunhomeAPI(
                    self.username, self.password, ""
                )  # Dummy mqtt values for now
                await self.api.get_bearer_token()  # Attempt to fetch the token
                # If authentication succeeds, move to the next step
                return await self.async_step_device_id()
            except Exception:
                _LOGGER.error(
                    "Failed to authenticate with the provided username/password."
                )
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
        """Handle the step to optionally capture the device ID."""
        if user_input is not None:
            self.device_id = user_input.get("device_id")  # Device ID is optional
            # Proceed with finishing the config flow
            return self._create_entry()

        # Ask for device ID if not provided
        return self.async_show_form(
            step_id="device_id",
            data_schema=vol.Schema(
                {
                    vol.Optional("device_id", default=""): cv.string,
                }
            ),
            description_placeholders={"device_id": self.device_id or "None"},
        )

    def _create_entry(self):
        """Create the config entry."""
        return self.async_create_entry(
            title="ESY Sunhome",
            data={
                "username": self.username,
                "password": self.password,
                "device_id": self.device_id,
            },
        )

    async def async_step_import(self, user_input=None):
        """Handle importing configuration."""
        return await self.async_step_user(user_input)


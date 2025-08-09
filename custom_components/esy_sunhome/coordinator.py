import contextlib
from datetime import timedelta
import logging
import aiohttp

from homeassistant.const import CONF_UNIQUE_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, CONF_DEVICE_ID, CONF_USERNAME, CONF_PASSWORD
from .battery import EsySunhomeBattery, MessageListener, BatteryState

_LOGGER = logging.getLogger(__name__)


class EsySunhomeMessageListener(MessageListener):
    """Process incoming messages."""

    def __init__(self, coordinator) -> None:
        """Initialise listener."""
        self.coordinator = coordinator

    def on_message(self, state: BatteryState) -> None:
        """Handle incoming messages."""
        with contextlib.suppress(AttributeError):
            self.coordinator.set_update_interval(True)
        self.coordinator.async_set_updated_data(state)


class EsySunhomeCoordinator(DataUpdateCoordinator[BatteryState]):
    """Class to fetch data from EsySunhome Battery Controller."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize coordinator."""

        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name=DOMAIN,
            always_update=False,
        )

        self.api = EsySunhomeBattery(
            self.config_entry.data[CONF_USERNAME],
            self.config_entry.data[CONF_PASSWORD],
            self.config_entry.data.get(CONF_DEVICE_ID),
        )
        self.api.connect(EsySunhomeMessageListener(self))
        self._fast_updates = True
        self._cancel_updates = None

        self.set_update_interval(fast=True)

    def set_update_interval(self, fast: bool) -> None:
        """Adjust the update interval."""

        # timer is already correct
        if self._cancel_updates and self._fast_updates == fast:
            return

        # cancel existing timer and start a new one
        if self._cancel_updates:
            self._cancel_updates()

        self._cancel_updates = async_track_time_interval(
            self.hass,
            self._async_request_update,
            timedelta(seconds=30),
            cancel_on_shutdown=True,
        )
        self._fast_updates = fast

    async def _async_request_update(self, _):
        await self.api.request_update()

    async def shutdown(self):
        """Shutdown the API."""
        if self.api:
            await self.api.disconnect()

"""ESY Sunhome Data Update Coordinator."""

from __future__ import annotations

import contextlib
from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    DOMAIN,
    CONF_DEVICE_ID,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_USER_ID,
    CONF_ENABLE_POLLING,
    DEFAULT_ENABLE_POLLING,
)
from .battery import EsySunhomeBattery, MessageListener, InverterState
from .esysunhome import ESYSunhomeAPI

_LOGGER = logging.getLogger(__name__)


class EsySunhomeMessageListener(MessageListener):
    """Process incoming MQTT messages."""

    def __init__(self, coordinator: EsySunhomeCoordinator) -> None:
        """Initialize listener."""
        self.coordinator = coordinator

    def on_message(self, state: InverterState) -> None:
        """Handle incoming messages."""
        with contextlib.suppress(AttributeError):
            self.coordinator.set_update_interval(True)
        self.coordinator.async_set_updated_data(state)


class EsySunhomeCoordinator(DataUpdateCoordinator[InverterState]):
    """Class to fetch data from ESY Sunhome Inverter via MQTT."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name=DOMAIN,
            always_update=False,
        )

        # Get configuration from config entry
        username = self.config_entry.data[CONF_USERNAME]
        password = self.config_entry.data[CONF_PASSWORD]
        device_id = self.config_entry.data.get(CONF_DEVICE_ID)
        user_id = self.config_entry.data.get(CONF_USER_ID)

        # Initialize battery controller with v2.0.0 binary protocol
        self.api = EsySunhomeBattery(
            username=username,
            password=password,
            device_id=device_id,
            user_id=user_id,
        )

        # Initialize REST API client for mode setting and other operations
        self._rest_api = ESYSunhomeAPI(username, password, device_id)
        self.api.api = self._rest_api  # Link REST API to battery controller

        # Connect to MQTT
        self.api.connect(EsySunhomeMessageListener(self))

        # Update interval management
        self._fast_updates = True
        self._cancel_updates = None
        self._polling_enabled = self.config_entry.options.get(
            CONF_ENABLE_POLLING, DEFAULT_ENABLE_POLLING
        )

        self.set_update_interval(fast=True)

        _LOGGER.info(
            "Coordinator initialized for device %s (user_id: %s)",
            device_id,
            user_id or "not set",
        )

    def set_polling_enabled(self, enabled: bool) -> None:
        """Enable or disable API polling."""
        self._polling_enabled = enabled
        _LOGGER.info("API polling %s", "enabled" if enabled else "disabled")

    def set_update_interval(self, fast: bool) -> None:
        """Adjust the update interval.

        For v2.0.0, the inverter pushes data automatically via MQTT,
        so polling is mainly for backup/fallback purposes.
        """
        # Timer is already correct
        if self._cancel_updates and self._fast_updates == fast:
            return

        # Cancel existing timer and start a new one
        if self._cancel_updates:
            self._cancel_updates()

        self._cancel_updates = async_track_time_interval(
            self.hass,
            self._async_request_update,
            timedelta(seconds=30),  # Longer interval since MQTT pushes data
            cancel_on_shutdown=True,
        )
        self._fast_updates = fast

    async def _async_request_update(self, _) -> None:
        """Request update - only if polling is enabled.

        For v2.0.0, the inverter pushes data automatically via MQTT,
        so this is mainly for fallback purposes.
        """
        if self._polling_enabled:
            try:
                await self.api.request_update()
            except Exception as e:
                _LOGGER.debug("Update request failed: %s", e)
        else:
            _LOGGER.debug("Polling disabled, skipping update request")

    async def shutdown(self) -> None:
        """Shutdown the coordinator."""
        if self._cancel_updates:
            self._cancel_updates()
            self._cancel_updates = None

        if self.api:
            await self.api.disconnect()

        if self._rest_api:
            await self._rest_api.close_session()

        _LOGGER.info("Coordinator shutdown complete")

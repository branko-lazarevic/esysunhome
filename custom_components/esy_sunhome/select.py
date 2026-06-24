import asyncio
import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.exceptions import HomeAssistantError

from .battery import BatteryState
from .entity import EsySunhomeEntity
from .const import (
    ATTR_SCHEDULE_MODE,
    CONF_MODE_CHANGE_METHOD,
    MODE_CHANGE_MQTT,
    DEFAULT_MODE_CHANGE_METHOD,
)

_LOGGER = logging.getLogger(__name__)

# Configuration for retries and timeouts
MODE_CHANGE_TIMEOUT = 30  # Seconds to wait for MQTT confirmation
MAX_RETRIES = 2  # Number of retries after timeout (total attempts = 1 + MAX_RETRIES)

# Icons
ICON_NORMAL = "mdi:battery-sync-outline"
ICON_LOADING = "mdi:sync"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        [
            ModeSelect(coordinator=entry.runtime_data, config_entry=entry),
        ]
    )


class ModeSelect(EsySunhomeEntity, SelectEntity):
    """Represents the operating mode for base modes (Regular, Emergency, Sell).
    When BEM (Battery Energy Management) is active, this entity becomes
    unavailable because the server-side scheduler controls mode changes.
    """

    _attr_translation_key = ATTR_SCHEDULE_MODE
    _attr_options = list(BatteryState.modes.values())
    _attr_current_option = _attr_options[0]
    _attr_name = "Operating Mode"
    _attr_icon = ICON_NORMAL

    def __init__(self, coordinator, config_entry: ConfigEntry):
        """Initialize the mode select entity."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._pending_mode_name = None     # Mode NAME we're trying to change to
        self._retry_count = 0
        self._confirmation_timeout = None
        self._is_loading = False

    @property
    def available(self) -> bool:
        """Unavailable when BEM is active — server controls mode changes."""
        return super().available and not self.coordinator.bem_active

    @property
    def _use_mqtt(self) -> bool:
        """Check if MQTT should be used for mode changes instead of API."""
        method = self._config_entry.options.get(
            CONF_MODE_CHANGE_METHOD, DEFAULT_MODE_CHANGE_METHOD
        )
        return method == MODE_CHANGE_MQTT

    @property
    def icon(self) -> str:
        """Return the icon based on loading state."""
        return ICON_LOADING if self._is_loading else ICON_NORMAL

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra state attributes including loading state."""
        return {
            "loading": self._is_loading,
            "pending_mode": self._pending_mode_name,
            "retry_count": self._retry_count if self._is_loading else 0,
            "mode_change_method": "mqtt" if self._use_mqtt else "api",
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator.

        MQTT register 5 (systemRunMode) is the source of truth for the
        current base mode. We use it to confirm pending changes or
        update the display.
        """
        try:
            mqtt_mode_name = getattr(self.coordinator.data, ATTR_SCHEDULE_MODE, None)
        except (AttributeError, KeyError, TypeError):
            mqtt_mode_name = None

        if mqtt_mode_name is None:
            return

        # Only track known base modes
        if mqtt_mode_name not in self._attr_options:
            _LOGGER.debug(
                "MQTT reports mode '%s' not in base modes, ignoring for select",
                mqtt_mode_name,
            )
            self.async_write_ha_state()
            return

        if self._pending_mode_name:
            if mqtt_mode_name == self._pending_mode_name:
                _LOGGER.info("Mode change confirmed via MQTT: %s", mqtt_mode_name)
                self._attr_current_option = mqtt_mode_name
                self._clear_pending(success=True)
            else:
                _LOGGER.debug(
                    "Waiting for MQTT confirmation. Current: %s, Requested: %s",
                    mqtt_mode_name, self._pending_mode_name,
                )
        else:
            self._attr_current_option = mqtt_mode_name

        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Set operating mode with optimistic update and retry logic.

        Uses MQTT or API based on the mode_change_method config option.

        Args:
            option: The operating mode name to set
        """
        if self.coordinator.bem_active:
            raise HomeAssistantError(
                "Cannot change operating mode while Battery Energy Management is active"
            )

        # Resolve the mode code for the selected method
        if self._use_mqtt:
            mode_code = BatteryState.modes_to_mqtt.get(option)
        else:
            mode_code = BatteryState.modes_to_api.get(option)

        if mode_code is None:
            raise HomeAssistantError(f"Invalid operating mode: {option}")

        if option == self._attr_current_option:
            _LOGGER.info("Already in mode %s, no change needed", option)
            return

        _LOGGER.info(
            "Mode change: %s -> %s (code=%s, method=%s)",
            self._attr_current_option, option, mode_code,
            "mqtt" if self._use_mqtt else "api",
        )

        # Optimistic update
        self._attr_current_option = option
        self._pending_mode_name = option
        self._retry_count = 0
        self._is_loading = True
        self.async_write_ha_state()

        await self._send_mode_change(option, mode_code)

    async def _send_mode_change(self, mode_name: str, mode_code: int) -> None:
        """Send the mode change command via MQTT or API.

        Args:
            mode_name: Display name of the target mode
            mode_code: MQTT register value or API code depending on method
        """
        try:
            if self._use_mqtt:
                success = await self.coordinator.set_mode_mqtt(mode_code)
                if not success:
                    raise Exception("MQTT not connected")
            else:
                await self.coordinator.api.set_mode(mode_code)

            _LOGGER.info(
                "Mode change command sent: %s (attempt %d/%d, method=%s)",
                mode_name, self._retry_count + 1, MAX_RETRIES + 1,
                "mqtt" if self._use_mqtt else "api",
            )

            self.hass.bus.async_fire(
                "esy_sunhome_mode_change_requested",
                {
                    "device_id": self.coordinator.api.device_id,
                    "mode": mode_name,
                    "mode_code": mode_code,
                    "method": "mqtt" if self._use_mqtt else "api",
                    "attempt": self._retry_count + 1,
                },
            )

            # Schedule timeout for MQTT confirmation
            self._schedule_confirmation_timeout(mode_name, mode_code)

        except Exception as err:
            _LOGGER.error("Failed to send mode change for %s: %s", mode_name, err)
            self._revert_to_actual()
            self.async_write_ha_state()
            raise HomeAssistantError(
                f"Failed to change operating mode to {mode_name}: {err}"
            ) from err

    def _schedule_confirmation_timeout(self, mode_name: str, mode_code: int) -> None:
        """Schedule a timeout to retry or revert if MQTT doesn't confirm."""
        if self._confirmation_timeout:
            self._confirmation_timeout.cancel()

        async def _on_timeout():
            if not self._pending_mode_name:
                return  # Already confirmed

            self._retry_count += 1

            if self._retry_count <= MAX_RETRIES:
                _LOGGER.warning(
                    "Mode change to %s timed out after %ds. Retry %d/%d",
                    mode_name, MODE_CHANGE_TIMEOUT,
                    self._retry_count + 1, MAX_RETRIES + 1,
                )

                self.hass.bus.async_fire(
                    "esy_sunhome_mode_change_retry",
                    {
                        "device_id": self.coordinator.api.device_id,
                        "mode": mode_name,
                        "mode_code": mode_code,
                        "attempt": self._retry_count + 1,
                        "max_attempts": MAX_RETRIES + 1,
                    },
                )

                try:
                    await self._send_mode_change(mode_name, mode_code)
                except Exception:
                    self._revert_to_actual()
                    self.async_write_ha_state()
            else:
                _LOGGER.error(
                    "Mode change to %s failed after %d attempts (%ds total)",
                    mode_name, MAX_RETRIES + 1,
                    (MAX_RETRIES + 1) * MODE_CHANGE_TIMEOUT,
                )

                self.hass.bus.async_fire(
                    "esy_sunhome_mode_change_timeout",
                    {
                        "device_id": self.coordinator.api.device_id,
                        "mode": mode_name,
                        "mode_code": mode_code,
                        "total_attempts": MAX_RETRIES + 1,
                    },
                )

                self._revert_to_actual()
                self.async_write_ha_state()

        self._confirmation_timeout = self.hass.loop.call_later(
            MODE_CHANGE_TIMEOUT,
            lambda: asyncio.create_task(_on_timeout()),
        )

    def _revert_to_actual(self) -> None:
        """Revert display to the actual MQTT-reported base mode."""
        try:
            actual = getattr(self.coordinator.data, ATTR_SCHEDULE_MODE, None)
            if actual and actual in self._attr_options:
                self._attr_current_option = actual
        except (AttributeError, KeyError, TypeError):
            pass
        self._clear_pending(success=False)

    def _clear_pending(self, success: bool = True) -> None:
        """Clear the pending state and restore normal icon."""
        old_mode = self._pending_mode_name

        self._pending_mode_name = None
        self._retry_count = 0
        self._is_loading = False

        if self._confirmation_timeout:
            self._confirmation_timeout.cancel()
            self._confirmation_timeout = None

        if success and old_mode:
            _LOGGER.info("Mode change to %s completed successfully", old_mode)
            self.hass.bus.async_fire(
                "esy_sunhome_mode_changed",
                {
                    "device_id": self.coordinator.api.device_id,
                    "mode": old_mode,
                    "success": True,
                },
            )

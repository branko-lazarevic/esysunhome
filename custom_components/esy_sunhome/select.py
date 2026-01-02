import asyncio
import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.exceptions import HomeAssistantError

from .battery import BatteryState
from .entity import EsySunhomeEntity
from .const import ATTR_SCHEDULE_MODE

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
            ModeSelect(coordinator=entry.runtime_data),
        ]
    )


class ModeSelect(EsySunhomeEntity, SelectEntity):
    """Represents the operating mode with optimistic updates during retries only."""

    _attr_translation_key = ATTR_SCHEDULE_MODE
    _attr_options = list(BatteryState.modes.values())
    _attr_current_option = _attr_options[0]
    _attr_name = "Operating Mode"
    _attr_icon = ICON_NORMAL

    def __init__(self, coordinator):
        """Initialize the mode select entity."""
        super().__init__(coordinator)
        self._pending_mode_name = None     # Mode NAME we're trying to change to (string)
        self._pending_mode_key = None      # Mode KEY we're trying to change to (int)
        self._retry_count = 0
        self._confirmation_timeout = None
        self._actual_mqtt_mode_name = None # What MQTT actually says (string)
        self._is_loading = False

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
            "actual_mode": self._actual_mqtt_mode_name,
            "retry_count": self._retry_count if self._is_loading else 0,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator.
        
        MQTT updates tell us the actual state of the battery.
        We use this to confirm pending changes or update the display.
        """
        # Try to get the mode name from MQTT data
        try:
            # schedule_mode returns the mode NAME (string like "Regular Mode")
            mqtt_mode_name = getattr(self.coordinator.data, ATTR_SCHEDULE_MODE, None)
        except (AttributeError, KeyError, TypeError) as e:
            _LOGGER.debug(f"Could not get mode from coordinator data: {e}")
            mqtt_mode_name = None
        
        if mqtt_mode_name is None:
            # No mode data available yet
            return
        
        # Always track the actual MQTT state
        self._actual_mqtt_mode_name = mqtt_mode_name
        
        # Check if we have a pending mode change
        if self._pending_mode_name:
            if mqtt_mode_name == self._pending_mode_name:
                # Success! MQTT confirmed our requested mode
                _LOGGER.info(
                    f"✅ Mode change confirmed via MQTT: {mqtt_mode_name} "
                    f"after {self._retry_count} retries"
                )
                self._attr_current_option = mqtt_mode_name
                self._clear_pending_state(success=True)
            else:
                # MQTT shows something else - keep waiting unless timeout handles it
                _LOGGER.debug(
                    f"Waiting for MQTT confirmation. Current: {mqtt_mode_name}, "
                    f"Requested: {self._pending_mode_name}"
                )
                # Don't update display while pending - keep showing optimistic mode
        else:
            # Not pending - show what MQTT says
            self._attr_current_option = mqtt_mode_name
        
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Set operating mode with optimistic update during retries only.
        
        Shows the new mode optimistically while retrying, but reverts to
        actual MQTT state if all retries fail.
        
        Args:
            option: The operating mode name to set
            
        Raises:
            HomeAssistantError: If mode change fails after retries
        """
        mode_key = self.get_mode_key(option)
        
        if mode_key is None:
            error_msg = f"Invalid operating mode: {option}"
            _LOGGER.error(error_msg)
            raise HomeAssistantError(error_msg)
        
        # Check if already in this mode
        if self._actual_mqtt_mode_name == option:
            _LOGGER.info(f"Already in mode {option}, no change needed")
            return
        
        _LOGGER.info(
            f"🔄 User requested mode change: {self._actual_mqtt_mode_name} → {option} "
            f"(code: {mode_key})"
        )
        
        # Optimistically update the displayed mode immediately
        # This prevents other automations from thinking it's still in the old mode
        self._attr_current_option = option
        
        # Set pending state (shows loading icon)
        self._set_pending_state(option, mode_key)
        
        # Send the initial API request
        await self._attempt_mode_change(option, mode_key)

    async def _attempt_mode_change(self, mode_name: str, mode_key: int) -> None:
        """Attempt to change mode via MQTT command directly to inverter.
        
        Based on traffic analysis, the app uses MQTT to directly command the
        inverter. The API is likely just for cloud sync/logging.
        
        Args:
            mode_name: The mode name being changed to (string)
            mode_key: The mode code being changed to (int)
        """
        try:
            # Send MQTT command directly to the inverter
            mqtt_success = await self.coordinator.set_mode_mqtt(mode_key)
            
            if mqtt_success:
                _LOGGER.info(
                    f"✓ MQTT command sent for mode change to: {mode_name}. "
                    f"Waiting for confirmation... (attempt {self._retry_count + 1}/{MAX_RETRIES + 1})"
                )
            else:
                _LOGGER.warning(f"MQTT command failed for mode change to: {mode_name}")
                raise Exception("MQTT publish failed")
            
            # Fire event for request success
            self.hass.bus.async_fire(
                "esy_sunhome_mode_change_requested",
                {
                    "device_id": self.coordinator.api.device_id,
                    "mode": mode_name,
                    "mode_code": mode_key,
                    "status": "mqtt_sent",
                    "attempt": self._retry_count + 1
                }
            )
            
            # Schedule timeout to check for MQTT confirmation
            self._schedule_confirmation_timeout(mode_name, mode_key)
            
        except Exception as err:
            error_msg = f"Failed to send mode change command for {mode_name}: {err}"
            _LOGGER.error(error_msg)
            
            # Revert to actual MQTT state on error
            if self._actual_mqtt_mode_name:
                self._attr_current_option = self._actual_mqtt_mode_name
            
            # Restore normal state immediately on error
            self._clear_pending_state(success=False)
            
            # Fire failure event
            self.hass.bus.async_fire(
                "esy_sunhome_mode_changed",
                {
                    "device_id": self.coordinator.api.device_id,
                    "mode": mode_name,
                    "mode_code": mode_key,
                    "success": False,
                    "error": str(err)
                }
            )
            
            self.async_write_ha_state()
            
            # Re-raise as HomeAssistantError so UI shows the error
            raise HomeAssistantError(
                f"Failed to change operating mode to {mode_name}. "
                f"Error: {err}"
            ) from err

    def _set_pending_state(self, mode_name: str, mode_key: int) -> None:
        """Set the entity to pending state (shows loading icon).
        
        Args:
            mode_name: The mode name being changed to (string)
            mode_key: The mode code being changed to (int)
        """
        self._pending_mode_name = mode_name
        self._pending_mode_key = mode_key
        self._retry_count = 0
        self._is_loading = True
        
        self.async_write_ha_state()
        
        _LOGGER.debug(
            f"🔄 Loading state set for mode change to: {mode_name}. "
            f"Showing optimistic mode to prevent automation conflicts."
        )

    def _clear_pending_state(self, success: bool = True) -> None:
        """Clear the pending state and restore normal icon.
        
        Args:
            success: Whether the mode change was successful
        """
        if self._pending_mode_name is None and not self._is_loading:
            return  # Nothing to clear
        
        old_mode = self._pending_mode_name
        old_retry_count = self._retry_count
        
        self._pending_mode_name = None
        self._pending_mode_key = None
        self._retry_count = 0
        self._is_loading = False
        
        # Cancel any pending timeout
        if self._confirmation_timeout:
            self._confirmation_timeout.cancel()
            self._confirmation_timeout = None
        
        if success and old_mode:
            _LOGGER.info(f"✅ Mode change to {old_mode} completed successfully")
            
            # Fire success event
            self.hass.bus.async_fire(
                "esy_sunhome_mode_changed",
                {
                    "device_id": self.coordinator.api.device_id,
                    "mode": old_mode,
                    "success": True,
                    "total_attempts": old_retry_count + 1
                }
            )

    def _schedule_confirmation_timeout(self, mode_name: str, mode_key: int) -> None:
        """Schedule a timeout to retry or revert if MQTT doesn't confirm.
        
        Args:
            mode_name: The mode name being changed to (string)
            mode_key: The mode code being changed to (int)
        """
        async def _timeout_callback():
            """Handle timeout waiting for MQTT confirmation."""
            if not self._pending_mode_name:
                return  # Already confirmed or cleared
            
            self._retry_count += 1
            
            if self._retry_count <= MAX_RETRIES:
                # Still have retries left - try again
                _LOGGER.warning(
                    f"⏱️ Mode change to {mode_name} timed out after {MODE_CHANGE_TIMEOUT}s. "
                    f"Retrying... (attempt {self._retry_count + 1}/{MAX_RETRIES + 1})"
                )
                
                # Fire retry event
                self.hass.bus.async_fire(
                    "esy_sunhome_mode_change_retry",
                    {
                        "device_id": self.coordinator.api.device_id,
                        "mode": mode_name,
                        "mode_code": mode_key,
                        "attempt": self._retry_count + 1,
                        "max_attempts": MAX_RETRIES + 1
                    }
                )
                
                # Retry MQTT command
                try:
                    mqtt_success = await self.coordinator.set_mode_mqtt(mode_key)
                    if mqtt_success:
                        _LOGGER.info(
                            f"✓ Retry MQTT command sent for mode: {mode_name} "
                            f"(attempt {self._retry_count + 1}/{MAX_RETRIES + 1})"
                        )
                    else:
                        raise Exception("MQTT publish failed")
                    
                    # Schedule another timeout
                    self._schedule_confirmation_timeout(mode_name, mode_key)
                    
                except Exception as err:
                    _LOGGER.error(f"❌ Retry {self._retry_count} failed: {err}")
                    
                    # Revert to actual MQTT state
                    if self._actual_mqtt_mode_name:
                        self._attr_current_option = self._actual_mqtt_mode_name
                    
                    self._clear_pending_state(success=False)
                    self.async_write_ha_state()
            else:
                # No more retries - revert to actual battery state
                actual_mode = self._actual_mqtt_mode_name or "Unknown"
                
                _LOGGER.error(
                    f"❌ Mode change to {mode_name} failed after {MAX_RETRIES + 1} attempts "
                    f"({(MAX_RETRIES + 1) * MODE_CHANGE_TIMEOUT}s total). "
                    f"Reverting to actual battery state: {actual_mode}"
                )
                
                # Revert display to what MQTT actually says
                if self._actual_mqtt_mode_name:
                    self._attr_current_option = self._actual_mqtt_mode_name
                
                # Fire final timeout event
                self.hass.bus.async_fire(
                    "esy_sunhome_mode_change_timeout",
                    {
                        "device_id": self.coordinator.api.device_id,
                        "mode": mode_name,
                        "mode_code": mode_key,
                        "total_attempts": self._retry_count + 1,
                        "timeout_seconds": (MAX_RETRIES + 1) * MODE_CHANGE_TIMEOUT,
                        "reverted_to_actual": True,
                        "actual_mode": actual_mode
                    }
                )
                
                # Stop loading and revert to actual state
                self._clear_pending_state(success=False)
                self.async_write_ha_state()
        
        # Cancel any existing timeout
        if self._confirmation_timeout:
            self._confirmation_timeout.cancel()
        
        # Schedule new timeout
        self._confirmation_timeout = self.hass.loop.call_later(
            MODE_CHANGE_TIMEOUT,
            lambda: asyncio.create_task(_timeout_callback())
        )
        
        _LOGGER.debug(
            f"⏲️ Scheduled {MODE_CHANGE_TIMEOUT}s timeout for mode change confirmation "
            f"(retry {self._retry_count + 1}/{MAX_RETRIES + 1})"
        )

    def get_mode_key(self, value: str) -> int:
        """Get the MQTT register value to write for a given mode name.
        
        Based on APK analysis, the MQTT systemRunMode register value is NOT
        the same as the display code. The mapping is:
        - Regular Mode -> write 1
        - Emergency Mode -> write 4
        - Electricity Sell Mode -> write 3
        - Battery Energy Management -> write 5 (may need adjustment)
        
        Args:
            value: The operating mode name (e.g., "Regular Mode")
            
        Returns:
            The MQTT register value to write, or None if not found
        """
        return BatteryState.modes_to_mqtt.get(value)

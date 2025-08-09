from homeassistant.const import CONF_UNIQUE_ID
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EsySunhomeCoordinator

class EsySunhomeEntity(CoordinatorEntity[EsySunhomeCoordinator]):
    """Implementation of the base EsySunhome Entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: EsySunhomeCoordinator) -> None:
        """Initialize the EsySunhome Entity."""

        super().__init__(coordinator=coordinator)
        self._attr_unique_id = (
            f"{coordinator.api.unique_id}_{self._attr_translation_key}"
        )

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.data[CONF_UNIQUE_ID])},
            manufacturer="EsySunhome",
            model="HM6",
        )
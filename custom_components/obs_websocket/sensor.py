"""Sensor platform for OBS WebSocket."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from . import OBSConfigEntry, OBSCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: OBSConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up OBS WebSocket sensors from a config entry."""
    coordinator = entry.runtime_data.coordinator

    async_add_entities(
        [
            OBSStreamStatusSensor(coordinator, entry),
            OBSStreamServiceSensor(coordinator, entry),
        ]
    )


class OBSSensorBase(CoordinatorEntity[OBSCoordinator], SensorEntity):
    """Base class for OBS sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: OBSCoordinator, entry: OBSConfigEntry) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"OBS Studio ({entry.data['host']})",
            manufacturer="OBS Project",
            sw_version=None,
        )


class OBSStreamStatusSensor(OBSSensorBase):
    """Sensor showing OBS stream status."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["idle", "streaming", "reconnecting"]
    _attr_translation_key = "stream_status"

    def __init__(self, coordinator: OBSCoordinator, entry: OBSConfigEntry) -> None:
        """Initialize."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_stream_status"

    @property
    def native_value(self) -> str | None:
        """Return the stream state."""
        if self.coordinator.data is None:
            return None
        status = self.coordinator.data["stream_status"]
        if getattr(status, "output_reconnecting", False):
            return "reconnecting"
        if getattr(status, "output_active", False):
            return "streaming"
        return "idle"

    @property
    def extra_state_attributes(self) -> dict:
        """Return stream statistics."""
        if self.coordinator.data is None:
            return {}
        status = self.coordinator.data["stream_status"]
        return {
            "output_bytes": getattr(status, "output_bytes", None),
            "output_duration": getattr(status, "output_duration", None),
            "output_timecode": getattr(status, "output_timecode", None),
            "output_skipped_frames": getattr(status, "output_skipped_frames", None),
            "output_total_frames": getattr(status, "output_total_frames", None),
            "output_congestion": getattr(status, "output_congestion", None),
        }


class OBSStreamServiceSensor(OBSSensorBase):
    """Sensor showing OBS stream service configuration."""

    _attr_translation_key = "stream_service"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: OBSCoordinator, entry: OBSConfigEntry) -> None:
        """Initialize."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_stream_service"

    @property
    def native_value(self) -> str | None:
        """Return the stream service type."""
        if self.coordinator.data is None:
            return None
        svc = self.coordinator.data["service_settings"]
        return getattr(svc, "stream_service_type", None)

    @property
    def extra_state_attributes(self) -> dict:
        """Return stream service settings."""
        if self.coordinator.data is None:
            return {}
        svc = self.coordinator.data["service_settings"]
        settings = getattr(svc, "stream_service_settings", {})
        return {"stream_service_settings": settings}

"""Sensor platform for OBS WebSocket."""

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up OBS WebSocket sensors from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    async_add_entities(
        [
            OBSStreamStatusSensor(coordinator, entry),
            OBSStreamServiceSensor(coordinator, entry),
        ]
    )


class OBSStreamStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing OBS stream status."""

    _attr_icon = "mdi:broadcast"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_stream_status"
        self._attr_name = "OBS Stream Status"

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


class OBSStreamServiceSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing OBS stream service configuration."""

    _attr_icon = "mdi:cog-play"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_stream_service"
        self._attr_name = "OBS Stream Service"

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

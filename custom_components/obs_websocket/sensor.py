"""Sensor platform for OBS WebSocket."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfDataRate,
    UnitOfInformation,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import OBSConfigEntry, OBSCoordinator, numeric_field
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(  # NOSONAR
    hass: HomeAssistant, entry: OBSConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up OBS WebSocket sensors from a config entry."""
    coordinator = entry.runtime_data.coordinator

    async_add_entities(
        [
            OBSStreamStatusSensor(coordinator, entry),
            OBSStreamServiceSensor(coordinator, entry),
            OBSRecordStatusSensor(coordinator, entry),
            *(OBSStatSensor(coordinator, entry, description) for description in STAT_SENSORS),
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
    _attr_options: ClassVar[list[str]] = ["idle", "streaming", "reconnecting"]
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
    def extra_state_attributes(self) -> dict[str, Any]:
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


class OBSRecordStatusSensor(OBSSensorBase):
    """Sensor showing OBS recording status."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = ["idle", "recording", "paused"]
    _attr_translation_key = "record_status"

    def __init__(self, coordinator: OBSCoordinator, entry: OBSConfigEntry) -> None:
        """Initialize."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_record_status"

    @property
    def native_value(self) -> str | None:
        """Return the recording state."""
        if self.coordinator.data is None:
            return None
        status = self.coordinator.data.get("record_status")
        if not getattr(status, "output_active", False):
            return "idle"
        if getattr(status, "output_paused", False):
            return "paused"
        return "recording"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return recording statistics."""
        if self.coordinator.data is None:
            return {}
        status = self.coordinator.data.get("record_status")
        return {
            "output_bytes": getattr(status, "output_bytes", None),
            "output_duration": getattr(status, "output_duration", None),
            "output_timecode": getattr(status, "output_timecode", None),
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
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return stream service settings."""
        if self.coordinator.data is None:
            return {}
        svc = self.coordinator.data["service_settings"]
        settings = getattr(svc, "stream_service_settings", {})
        return {"stream_service_settings": settings}


def _rate(key: str) -> Callable[[dict[str, Any]], float | None]:
    return lambda data: data.get("rates", {}).get(key)


def _stat(attr: str) -> Callable[[dict[str, Any]], float | None]:
    return lambda data: numeric_field(data.get("stats"), attr)


def _congestion(data: dict[str, Any]) -> float | None:
    stream = data.get("stream_status")
    congestion = numeric_field(stream, "output_congestion")
    if not getattr(stream, "output_active", False) or congestion is None:
        return None
    return round(congestion * 100, 1)


def _counters(obj_key: str, skipped: str, total: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Expose OBS's cumulative counters alongside a windowed percentage."""

    def attrs(data: dict[str, Any]) -> dict[str, Any]:
        obj = data.get(obj_key)
        return {"skipped_frames": numeric_field(obj, skipped), "total_frames": numeric_field(obj, total)}

    return attrs


@dataclass(frozen=True, kw_only=True)
class OBSStatSensorEntityDescription(SensorEntityDescription):
    """Describes a numeric OBS statistic."""

    value_fn: Callable[[dict[str, Any]], float | None]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


STAT_SENSORS: tuple[OBSStatSensorEntityDescription, ...] = (
    OBSStatSensorEntityDescription(
        key="active_fps",
        translation_key="active_fps",
        native_unit_of_measurement="fps",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_stat("active_fps"),
    ),
    OBSStatSensorEntityDescription(
        key="render_skipped_frames",
        translation_key="render_skipped_frames",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_rate("render_skipped_pct"),
        attrs_fn=_counters("stats", "render_skipped_frames", "render_total_frames"),
    ),
    OBSStatSensorEntityDescription(
        key="encoding_lagged_frames",
        translation_key="encoding_lagged_frames",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_rate("encoding_lag_pct"),
        attrs_fn=_counters("stats", "output_skipped_frames", "output_total_frames"),
    ),
    OBSStatSensorEntityDescription(
        key="stream_dropped_frames",
        translation_key="stream_dropped_frames",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_rate("stream_dropped_pct"),
        attrs_fn=_counters("stream_status", "output_skipped_frames", "output_total_frames"),
    ),
    OBSStatSensorEntityDescription(
        key="stream_congestion",
        translation_key="stream_congestion",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_congestion,
    ),
    OBSStatSensorEntityDescription(
        key="stream_bitrate",
        translation_key="stream_bitrate",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.KILOBITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_rate("stream_bitrate"),
    ),
    OBSStatSensorEntityDescription(
        key="available_disk_space",
        translation_key="available_disk_space",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_stat("available_disk_space"),
    ),
    OBSStatSensorEntityDescription(
        key="cpu_usage",
        translation_key="cpu_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_stat("cpu_usage"),
    ),
    OBSStatSensorEntityDescription(
        key="memory_usage",
        translation_key="memory_usage",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_stat("memory_usage"),
    ),
    OBSStatSensorEntityDescription(
        key="average_frame_render_time",
        translation_key="average_frame_render_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_stat("average_frame_render_time"),
    ),
)


class OBSStatSensor(OBSSensorBase):
    """A numeric OBS statistic: performance, stream health or disk space."""

    entity_description: OBSStatSensorEntityDescription

    def __init__(
        self,
        coordinator: OBSCoordinator,
        entry: OBSConfigEntry,
        description: OBSStatSensorEntityDescription,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def native_value(self) -> float | None:
        """Return the statistic."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the cumulative counters behind a windowed percentage."""
        if self.coordinator.data is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)

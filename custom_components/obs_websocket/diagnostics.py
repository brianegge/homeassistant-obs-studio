"""Diagnostics support for OBS WebSocket."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import OBSConfigEntry

TO_REDACT: set[str] = {"password", "key"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: OBSConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data.coordinator
    connection = entry.runtime_data.connection

    coordinator_data: dict[str, Any] = {}
    if coordinator.data:
        stream_status = coordinator.data.get("stream_status")
        service_settings = coordinator.data.get("service_settings")
        if stream_status:
            coordinator_data["stream_status"] = {
                "output_active": getattr(stream_status, "output_active", None),
                "output_reconnecting": getattr(stream_status, "output_reconnecting", None),
                "output_bytes": getattr(stream_status, "output_bytes", None),
                "output_duration": getattr(stream_status, "output_duration", None),
                "output_timecode": getattr(stream_status, "output_timecode", None),
                "output_skipped_frames": getattr(stream_status, "output_skipped_frames", None),
                "output_total_frames": getattr(stream_status, "output_total_frames", None),
                "output_congestion": getattr(stream_status, "output_congestion", None),
            }
        if service_settings:
            coordinator_data["service_settings"] = {
                "stream_service_type": getattr(service_settings, "stream_service_type", None),
                "stream_service_settings": getattr(service_settings, "stream_service_settings", {}),
            }

    return async_redact_data(
        {
            "config_entry": {
                "data": dict(entry.data),
                "unique_id": entry.unique_id,
            },
            "connection": {
                "host": connection.host,
                "connected": connection.connected,
            },
            "coordinator": {
                "last_update_success": coordinator.last_update_success,
                "data": coordinator_data,
            },
        },
        TO_REDACT,
    )

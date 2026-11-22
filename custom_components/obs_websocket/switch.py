"""Switch platform for OBS WebSocket: the virtual camera."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import OBSConfigEntry, OBSCoordinator
from .entity import OBSEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: OBSConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the OBS virtual camera switch from a config entry."""
    async_add_entities([OBSVirtualCameraSwitch(entry.runtime_data.coordinator, entry)])


class OBSVirtualCameraSwitch(OBSEntity, SwitchEntity):
    """Turns the OBS virtual camera on and off.

    Unavailable when OBS has no virtual camera (for example on Linux without
    the v4l2loopback module).
    """

    _attr_translation_key = "virtual_camera"

    def __init__(self, coordinator: OBSCoordinator, entry: OBSConfigEntry) -> None:
        """Initialize."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_virtual_camera"

    @property
    def available(self) -> bool:
        """Return False when OBS is unreachable or has no virtual camera."""
        return super().available and self.is_on is not None

    @property
    def is_on(self) -> bool | None:
        """Return whether the virtual camera is running."""
        return (self.coordinator.data or {}).get("virtual_cam")

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the virtual camera."""
        await self._async_send(self.coordinator.connection.async_start_virtual_cam(), "start_virtual_cam_failed")
        # OBS also sends VirtualcamStateChanged, which polls; this covers a missed event.
        await self.coordinator.async_virtual_cam_changed(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the virtual camera."""
        await self._async_send(self.coordinator.connection.async_stop_virtual_cam(), "stop_virtual_cam_failed")
        await self.coordinator.async_virtual_cam_changed(False)

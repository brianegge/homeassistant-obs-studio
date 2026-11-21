"""Switch platform for OBS WebSocket: the virtual camera."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import OBSConfigEntry, OBSCoordinator
from .const import DOMAIN

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: OBSConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the OBS virtual camera switch from a config entry."""
    async_add_entities([OBSVirtualCameraSwitch(entry.runtime_data.coordinator, entry)])


class OBSVirtualCameraSwitch(CoordinatorEntity[OBSCoordinator], SwitchEntity):
    """Turns the OBS virtual camera on and off.

    Unavailable when OBS has no virtual camera (for example on Linux without
    the v4l2loopback module).
    """

    _attr_has_entity_name = True
    _attr_translation_key = "virtual_camera"

    def __init__(self, coordinator: OBSCoordinator, entry: OBSConfigEntry) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_virtual_camera"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"OBS Studio ({entry.data['host']})",
            manufacturer="OBS Project",
            sw_version=None,
        )

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

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the virtual camera."""
        await self._async_send(self.coordinator.connection.async_stop_virtual_cam(), "stop_virtual_cam_failed")

    async def _async_send(self, request: Awaitable[None], error_key: str) -> None:
        connection = self.coordinator.connection
        try:
            await request
        except Exception as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=error_key,
                translation_placeholders={"host": connection.host, "error": str(err)},
            ) from err
        # OBS also sends VirtualcamStateChanged; this covers a missed event.
        await self.coordinator.async_request_refresh()

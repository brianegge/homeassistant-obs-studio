"""Camera platform for OBS WebSocket: a snapshot of the program output."""

from __future__ import annotations

import logging

from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import OBSConfigEntry, OBSCoordinator
from .const import DEFAULT_SNAPSHOT_SIZE, DOMAIN

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

# OBS accepts screenshot dimensions between 8 and 4096 pixels.
_MIN_SIZE = 8
_MAX_SIZE = 4096


async def async_setup_entry(
    hass: HomeAssistant, entry: OBSConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the OBS program camera from a config entry."""
    async_add_entities([OBSProgramCamera(entry.runtime_data.coordinator, entry)])


class OBSProgramCamera(CoordinatorEntity[OBSCoordinator], Camera):
    """Still image of what OBS is sending to program (the stream and recording).

    Each image is a GetSourceScreenshot of the current program scene, taken
    only when the frontend or an automation asks for one. Rendering a
    screenshot costs OBS some GPU time, so the entity is disabled by default.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "program"
    _attr_entity_registry_enabled_default = False
    _attr_content_type = "image/jpeg"

    def __init__(self, coordinator: OBSCoordinator, entry: OBSConfigEntry) -> None:
        """Initialize."""
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._attr_unique_id = f"{entry.entry_id}_program"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"OBS Studio ({entry.data['host']})",
            manufacturer="OBS Project",
            sw_version=None,
        )

    async def async_camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        """Return a JPEG of the program scene, scaled to fit the requested size."""
        size = max(width or 0, height or 0) or DEFAULT_SNAPSHOT_SIZE
        size = min(max(size, _MIN_SIZE), _MAX_SIZE)
        try:
            return await self.coordinator.connection.async_get_program_screenshot(size)
        except Exception as err:  # a missing frame is not an error worth raising
            _LOGGER.debug("Could not get a program screenshot from %s: %s", self.coordinator.connection.host, err)
            return None

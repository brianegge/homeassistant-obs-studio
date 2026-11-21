"""Base entity for the OBS WebSocket integration."""

from __future__ import annotations

from collections.abc import Awaitable

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import OBSConfigEntry, OBSCoordinator
from .const import DOMAIN


class OBSEntity(CoordinatorEntity[OBSCoordinator]):
    """An entity on the OBS Studio device, fed by the coordinator."""

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

    async def _async_send(self, request: Awaitable[None], error_key: str, **placeholders: str) -> None:
        """Await a command to OBS, raising a translated error if it fails.

        `error_key` is an exception key in strings.json. Its message gets
        `host` and `error`, plus any `placeholders`.
        """
        try:
            await request
        except Exception as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=error_key,
                translation_placeholders={
                    "host": self.coordinator.connection.host,
                    "error": str(err),
                    **placeholders,
                },
            ) from err

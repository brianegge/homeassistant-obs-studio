"""Select platform for OBS WebSocket: the program scene."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
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
    """Set up the OBS scene select from a config entry."""
    async_add_entities([OBSSceneSelect(entry.runtime_data.coordinator, entry)])


class OBSSceneSelect(CoordinatorEntity[OBSCoordinator], SelectEntity):
    """Shows and switches the scene OBS sends to program (the stream and recording).

    The options follow the scenes in the current scene collection, in the order
    of OBS's Scenes dock, and update when scenes are added, removed or renamed.
    In studio mode, choosing a scene sends it straight to program.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "scene"

    def __init__(self, coordinator: OBSCoordinator, entry: OBSConfigEntry) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_scene"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"OBS Studio ({entry.data['host']})",
            manufacturer="OBS Project",
            sw_version=None,
        )

    @property
    def options(self) -> list[str]:
        """Return the scene names."""
        if self.coordinator.data is None:
            return []
        return list(self.coordinator.data.get("scenes", {}).get("names", []))

    @property
    def current_option(self) -> str | None:
        """Return the current program scene."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("scenes", {}).get("current")

    async def async_select_option(self, option: str) -> None:
        """Switch the program output to the chosen scene."""
        connection = self.coordinator.connection
        try:
            await connection.async_set_program_scene(option)
        except Exception as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="set_scene_failed",
                translation_placeholders={"host": connection.host, "scene": option, "error": str(err)},
            ) from err
        # OBS also sends CurrentProgramSceneChanged; this covers a missed event.
        await self.coordinator.async_request_refresh()

"""Button platform for OBS WebSocket."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import OBSConfigEntry, OBSConnection, OBSCoordinator
from .entity import OBSEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class OBSButtonEntityDescription(ButtonEntityDescription):
    """Describes an OBS button: the request it sends and its error message."""

    press_fn: Callable[[OBSConnection], Awaitable[None]]
    error_key: str


BUTTONS: tuple[OBSButtonEntityDescription, ...] = (
    OBSButtonEntityDescription(
        key="start_stream",
        translation_key="start_stream",
        press_fn=lambda conn: conn.async_start_stream(),
        error_key="start_stream_failed",
    ),
    OBSButtonEntityDescription(
        key="stop_stream",
        translation_key="stop_stream",
        press_fn=lambda conn: conn.async_stop_stream(),
        error_key="stop_stream_failed",
    ),
    OBSButtonEntityDescription(
        key="start_record",
        translation_key="start_record",
        press_fn=lambda conn: conn.async_start_record(),
        error_key="start_record_failed",
    ),
    OBSButtonEntityDescription(
        key="stop_record",
        translation_key="stop_record",
        press_fn=lambda conn: conn.async_stop_record(),
        error_key="stop_record_failed",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: OBSConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up OBS WebSocket buttons from a config entry."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(OBSButton(coordinator, entry, description) for description in BUTTONS)


class OBSButton(OBSEntity, ButtonEntity):
    """A button that sends one request to OBS."""

    entity_description: OBSButtonEntityDescription

    def __init__(
        self,
        coordinator: OBSCoordinator,
        entry: OBSConfigEntry,
        description: OBSButtonEntityDescription,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    async def async_press(self) -> None:
        """Send the button's request to OBS."""
        description = self.entity_description
        await self._async_send(description.press_fn(self.coordinator.connection), description.error_key)

"""Tests for the OBS WebSocket scene select."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.const import ATTR_OPTION, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.obs_websocket import parse_scene_list

from .conftest import MOCK_HOST, make_scene_list

ENTITY_ID = "select.obs_studio_192_168_1_100_scene"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()


def test_parse_scene_list_matches_dock_order() -> None:
    """Scenes come back bottom first; parsing puts them in Scenes dock order."""
    parsed = parse_scene_list(make_scene_list(["Starting", "Live", "BRB"], current="BRB"))
    assert parsed == {"current": "BRB", "names": ["Starting", "Live", "BRB"]}


@pytest.mark.parametrize(
    "response",
    [
        None,
        SimpleNamespace(),
        SimpleNamespace(current_program_scene_name=None, scenes=None),
        SimpleNamespace(current_program_scene_name=3, scenes=[{"sceneIndex": 0}, "junk"]),
    ],
)
def test_parse_scene_list_tolerates_bad_responses(response: object) -> None:
    """Missing or malformed fields give no scenes rather than an error."""
    assert parse_scene_list(response) == {"current": None, "names": []}


@pytest.mark.usefixtures("mock_obsws")
async def test_select_shows_scenes_and_current(hass: HomeAssistant, mock_config_entry: MockConfigEntry) -> None:
    """The select lists the scenes and shows the program scene."""
    await _setup(hass, mock_config_entry)

    entity = er.async_get(hass).async_get(ENTITY_ID)
    assert entity is not None
    assert entity.unique_id == f"{mock_config_entry.entry_id}_scene"

    state = hass.states.get(ENTITY_ID)
    assert state.state == "Live"
    assert state.attributes["options"] == ["Starting", "Live", "BRB"]


@pytest.mark.usefixtures("mock_obsws")
async def test_select_follows_scene_changes(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_req_client: MagicMock
) -> None:
    """A changed program scene or scene list shows up on the next refresh."""
    await _setup(hass, mock_config_entry)

    mock_req_client.get_scene_list.return_value = make_scene_list(["Starting", "Live", "Outro"], current="Outro")
    await _refresh(hass, mock_config_entry)

    state = hass.states.get(ENTITY_ID)
    assert state.state == "Outro"
    assert state.attributes["options"] == ["Starting", "Live", "Outro"]


@pytest.mark.usefixtures("mock_obsws")
async def test_select_unknown_when_current_not_listed(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_req_client: MagicMock
) -> None:
    """A program scene missing from the list (mid collection change) reads as unknown."""
    mock_req_client.get_scene_list.return_value = make_scene_list(["A", "B"], current="Gone")
    await _setup(hass, mock_config_entry)

    assert hass.states.get(ENTITY_ID).state == STATE_UNKNOWN


@pytest.mark.usefixtures("mock_obsws")
async def test_select_option_switches_scene(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_req_client: MagicMock
) -> None:
    """Choosing a scene sets the program scene, then refreshes."""
    await _setup(hass, mock_config_entry)
    polls = mock_req_client.get_scene_list.call_count

    await hass.services.async_call(
        "select", "select_option", {"entity_id": ENTITY_ID, ATTR_OPTION: "BRB"}, blocking=True
    )
    await hass.async_block_till_done()

    mock_req_client.set_current_program_scene.assert_called_once_with("BRB")
    assert mock_req_client.get_scene_list.call_count > polls


@pytest.mark.usefixtures("mock_obsws")
async def test_select_rejects_unknown_scene(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_req_client: MagicMock
) -> None:
    """Home Assistant rejects a scene that is not in the list before OBS is asked."""
    await _setup(hass, mock_config_entry)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "select", "select_option", {"entity_id": ENTITY_ID, ATTR_OPTION: "Nope"}, blocking=True
        )
    mock_req_client.set_current_program_scene.assert_not_called()


@pytest.mark.usefixtures("mock_obsws")
async def test_select_option_failure_raises_translated_error(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_req_client: MagicMock
) -> None:
    """A failed scene switch raises HomeAssistantError with a translated message."""
    await _setup(hass, mock_config_entry)
    mock_req_client.set_current_program_scene.side_effect = Exception("boom")

    with pytest.raises(HomeAssistantError) as exc_info:
        await hass.services.async_call(
            "select", "select_option", {"entity_id": ENTITY_ID, ATTR_OPTION: "BRB"}, blocking=True
        )

    assert exc_info.value.translation_key == "set_scene_failed"
    assert str(exc_info.value) == f"Failed to switch OBS at {MOCK_HOST} to scene BRB: boom"


@pytest.mark.usefixtures("mock_obsws")
async def test_select_unavailable_when_obs_unreachable(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_req_client: MagicMock
) -> None:
    """The select goes unavailable with the rest of the device."""
    await _setup(hass, mock_config_entry)

    mock_req_client.get_scene_list.side_effect = ConnectionError("socket closed")
    await _refresh(hass, mock_config_entry)

    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE

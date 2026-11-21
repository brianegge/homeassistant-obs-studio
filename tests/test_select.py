"""Tests for the OBS WebSocket scene select."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.const import ATTR_OPTION, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.obs_websocket import parse_scene_list
from custom_components.obs_websocket.const import EVENT_REFRESH_COOLDOWN

from .conftest import MOCK_HOST, OBSSDKRequestError, make_scene_list, make_virtual_cam_status

ENTITY_ID = "select.obs_studio_192_168_1_100_scene"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()


async def _event(hass: HomeAssistant, entry: MockConfigEntry, event: str, **data: object) -> None:
    """Deliver an OBS event as the EventClient thread would, and let it be handled."""
    entry.runtime_data.connection._on_event(event, SimpleNamespace(**data))
    for _ in range(10):
        await asyncio.sleep(0)
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
    """Choosing a scene sets the program scene and shows it, without polling OBS."""
    await _setup(hass, mock_config_entry)
    polls = mock_req_client.get_scene_list.call_count

    await hass.services.async_call(
        "select", "select_option", {"entity_id": ENTITY_ID, ATTR_OPTION: "BRB"}, blocking=True
    )
    await hass.async_block_till_done()

    mock_req_client.set_current_program_scene.assert_called_once_with("BRB")
    assert hass.states.get(ENTITY_ID).state == "BRB"
    assert mock_req_client.get_scene_list.call_count == polls


@pytest.mark.usefixtures("mock_obsws")
async def test_program_scene_event_needs_no_request(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_req_client: MagicMock
) -> None:
    """CurrentProgramSceneChanged carries the scene name, so a scene cut asks OBS nothing."""
    await _setup(hass, mock_config_entry)
    mock_req_client.reset_mock()

    await _event(hass, mock_config_entry, "current_program_scene_changed", scene_name="BRB", scene_uuid="uuid-2")

    state = hass.states.get(ENTITY_ID)
    assert state.state == "BRB"
    assert state.attributes["options"] == ["Starting", "Live", "BRB"]
    assert mock_req_client.method_calls == []


@pytest.mark.usefixtures("mock_obsws")
@pytest.mark.parametrize("event", ["scene_list_changed", "scene_created", "scene_removed", "scene_name_changed"])
async def test_scene_list_event_fetches_only_the_scene_list(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_req_client: MagicMock, event: str
) -> None:
    """A scene list event re-reads the scene list, not stats and the rest of the poll."""
    await _setup(hass, mock_config_entry)
    mock_req_client.reset_mock()
    mock_req_client.get_scene_list.return_value = make_scene_list(["Starting", "Main", "BRB"], current="Main")

    await _event(hass, mock_config_entry, event)

    state = hass.states.get(ENTITY_ID)
    assert state.state == "Main"
    assert state.attributes["options"] == ["Starting", "Main", "BRB"]
    assert [call[0] for call in mock_req_client.method_calls] == ["get_scene_list"]


@pytest.mark.usefixtures("mock_obsws")
async def test_scene_list_event_while_obs_not_ready_keeps_entities(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_req_client: MagicMock
) -> None:
    """If OBS answers a scene list event's fetch with NotReady, nothing goes unavailable."""
    await _setup(hass, mock_config_entry)
    mock_req_client.get_scene_list.side_effect = OBSSDKRequestError("GetSceneList", 207)

    await _event(hass, mock_config_entry, "scene_removed")

    assert hass.states.get(ENTITY_ID).state == "Live"
    assert hass.states.get("sensor.obs_studio_192_168_1_100_stream_status").state == "idle"
    assert mock_config_entry.runtime_data.coordinator.last_update_success
    assert mock_config_entry.runtime_data.connection.connected


@pytest.mark.usefixtures("mock_obsws")
async def test_scene_collection_switch_waits_for_obs(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_req_client: MagicMock
) -> None:
    """Between CurrentSceneCollectionChanging and ...Changed OBS is not asked; after, it is."""
    await _setup(hass, mock_config_entry)
    mock_req_client.reset_mock()
    mock_req_client.get_scene_list.return_value = make_scene_list(["Intro", "Sermon"], current="Intro")

    await _event(hass, mock_config_entry, "current_scene_collection_changing")
    await _event(hass, mock_config_entry, "scene_removed")
    await _event(hass, mock_config_entry, "scene_created")
    assert mock_req_client.method_calls == []
    assert hass.states.get(ENTITY_ID).state == "Live"

    await _event(hass, mock_config_entry, "current_scene_collection_changed")
    # The burst above started the debounce cooldown; the fetch comes at its end.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=EVENT_REFRESH_COOLDOWN + 0.1))
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state.state == "Intro"
    assert state.attributes["options"] == ["Intro", "Sermon"]
    assert [call[0] for call in mock_req_client.method_calls] == ["get_scene_list"]


@pytest.mark.usefixtures("mock_obsws")
async def test_scene_event_during_poll_is_not_overwritten(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_req_client: MagicMock
) -> None:
    """A scene cut that lands while a poll is in flight survives the poll's older answer."""
    await _setup(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinator

    def _cut_mid_poll() -> SimpleNamespace:
        # Runs in the executor, after the poll has already read the scene list.
        asyncio.run_coroutine_threadsafe(coordinator.async_program_scene_changed("BRB"), hass.loop).result()
        return make_virtual_cam_status()

    mock_req_client.get_virtual_cam_status.side_effect = _cut_mid_poll
    await _refresh(hass, mock_config_entry)

    assert coordinator.last_update_success
    assert hass.states.get(ENTITY_ID).state == "BRB"


@pytest.mark.usefixtures("mock_obsws")
async def test_scene_events_do_not_postpone_the_poll(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_req_client: MagicMock
) -> None:
    """Scene cuts closer together than the heartbeat must not keep the poll from running."""
    await _setup(hass, mock_config_entry)
    polls = mock_req_client.get_stats.call_count

    for elapsed in (20, 40, 61):
        await _event(hass, mock_config_entry, "current_program_scene_changed", scene_name="BRB")
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=elapsed))
        await hass.async_block_till_done()

    assert mock_req_client.get_stats.call_count == polls + 1


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

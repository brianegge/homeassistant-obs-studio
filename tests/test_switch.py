"""Tests for the OBS WebSocket virtual camera switch."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import MOCK_HOST, NO_VIRTUAL_CAM_ERROR, OBSSDKRequestError, make_virtual_cam_status

ENTITY_ID = "switch.obs_studio_192_168_1_100_virtual_camera"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()


@pytest.mark.usefixtures("mock_obsws")
async def test_switch_registered(hass: HomeAssistant, mock_config_entry: MockConfigEntry) -> None:
    """The virtual camera switch is created with a stable unique ID."""
    await _setup(hass, mock_config_entry)

    entity = er.async_get(hass).async_get(ENTITY_ID)
    assert entity is not None
    assert entity.unique_id == f"{mock_config_entry.entry_id}_virtual_camera"
    assert hass.states.get(ENTITY_ID).state == STATE_OFF


@pytest.mark.usefixtures("mock_obsws")
async def test_switch_reflects_virtual_cam_status(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_req_client: MagicMock
) -> None:
    """The switch follows GetVirtualCamStatus."""
    mock_req_client.get_virtual_cam_status.return_value = make_virtual_cam_status(active=True)
    await _setup(hass, mock_config_entry)
    assert hass.states.get(ENTITY_ID).state == STATE_ON

    mock_req_client.get_virtual_cam_status.return_value = make_virtual_cam_status(active=False)
    await _refresh(hass, mock_config_entry)
    assert hass.states.get(ENTITY_ID).state == STATE_OFF


@pytest.mark.usefixtures("mock_obsws")
@pytest.mark.parametrize(("service", "method"), [("turn_on", "start_virtual_cam"), ("turn_off", "stop_virtual_cam")])
async def test_switch_sends_request(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_req_client: MagicMock,
    service: str,
    method: str,
) -> None:
    """Turning the switch on or off starts or stops the virtual camera, then refreshes."""
    await _setup(hass, mock_config_entry)
    polls = mock_req_client.get_virtual_cam_status.call_count

    await hass.services.async_call("switch", service, {"entity_id": ENTITY_ID}, blocking=True)
    await hass.async_block_till_done()

    getattr(mock_req_client, method).assert_called_once_with()
    assert mock_req_client.get_virtual_cam_status.call_count > polls


@pytest.mark.usefixtures("mock_obsws")
@pytest.mark.parametrize(
    ("service", "method", "translation_key", "verb"),
    [
        ("turn_on", "start_virtual_cam", "start_virtual_cam_failed", "start"),
        ("turn_off", "stop_virtual_cam", "stop_virtual_cam_failed", "stop"),
    ],
)
async def test_switch_failure_raises_translated_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_req_client: MagicMock,
    service: str,
    method: str,
    translation_key: str,
    verb: str,
) -> None:
    """A failed request raises HomeAssistantError with a translated message."""
    await _setup(hass, mock_config_entry)
    getattr(mock_req_client, method).side_effect = Exception("boom")

    with pytest.raises(HomeAssistantError) as exc_info:
        await hass.services.async_call("switch", service, {"entity_id": ENTITY_ID}, blocking=True)

    assert exc_info.value.translation_key == translation_key
    assert str(exc_info.value) == f"Failed to {verb} the virtual camera on OBS at {MOCK_HOST}: boom"


@pytest.mark.usefixtures("mock_obsws")
async def test_switch_unavailable_without_virtual_cam(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_req_client: MagicMock
) -> None:
    """With no virtual camera in OBS the switch is unavailable and OBS is not asked again.

    The rest of the integration keeps working.
    """
    mock_req_client.get_virtual_cam_status.side_effect = NO_VIRTUAL_CAM_ERROR
    await _setup(hass, mock_config_entry)

    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.obs_studio_192_168_1_100_stream_status").state == "idle"

    await _refresh(hass, mock_config_entry)
    mock_req_client.get_virtual_cam_status.assert_called_once()

    # A reconnect (OBS restarted, perhaps with a virtual camera now) asks again.
    mock_req_client.get_virtual_cam_status.side_effect = None
    mock_req_client.get_virtual_cam_status.return_value = make_virtual_cam_status(active=True)
    await mock_config_entry.runtime_data.connection.async_disconnect()
    await _refresh(hass, mock_config_entry)
    assert hass.states.get(ENTITY_ID).state == STATE_ON


@pytest.mark.parametrize(
    ("service", "method", "request_type", "code"),
    [
        ("turn_on", "start_virtual_cam", "StartVirtualCam", 500),
        ("turn_off", "stop_virtual_cam", "StopVirtualCam", 501),
    ],
)
async def test_switch_already_in_state_is_success(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_req_client: MagicMock,
    mock_obsws: MagicMock,
    service: str,
    method: str,
    request_type: str,
    code: int,
) -> None:
    """OBS answering "already running" to a start, or "not running" to a stop, is not a failure.

    The request is sent once on the same connection, and the state is refreshed.
    """
    await _setup(hass, mock_config_entry)
    getattr(mock_req_client, method).side_effect = OBSSDKRequestError(request_type, code)
    polls = mock_req_client.get_virtual_cam_status.call_count

    await hass.services.async_call("switch", service, {"entity_id": ENTITY_ID}, blocking=True)
    await hass.async_block_till_done()

    getattr(mock_req_client, method).assert_called_once_with()
    mock_req_client.disconnect.assert_not_called()
    mock_obsws.ReqClient.assert_called_once()
    assert mock_req_client.get_virtual_cam_status.call_count > polls


@pytest.mark.parametrize(
    ("service", "method", "request_type", "code"),
    [
        # The codes swapped: neither means "already in the state asked for".
        ("turn_on", "start_virtual_cam", "StartVirtualCam", 501),
        ("turn_off", "stop_virtual_cam", "StopVirtualCam", 500),
        ("turn_on", "start_virtual_cam", "StartVirtualCam", 604),
    ],
)
async def test_switch_other_request_error_fails_without_reconnect(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_req_client: MagicMock,
    mock_obsws: MagicMock,
    service: str,
    method: str,
    request_type: str,
    code: int,
) -> None:
    """Any other request error is raised, but OBS answered, so the connection is kept and not retried."""
    await _setup(hass, mock_config_entry)
    getattr(mock_req_client, method).side_effect = OBSSDKRequestError(request_type, code)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("switch", service, {"entity_id": ENTITY_ID}, blocking=True)

    getattr(mock_req_client, method).assert_called_once_with()
    mock_req_client.disconnect.assert_not_called()
    mock_obsws.ReqClient.assert_called_once()
    assert mock_config_entry.runtime_data.connection.connected


@pytest.mark.usefixtures("mock_obsws")
async def test_virtual_cam_passing_request_error_does_not_disable_switch(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_req_client: MagicMock
) -> None:
    """Only "no virtual camera" stops the polling; NotReady fails one poll and the next asks again."""
    await _setup(hass, mock_config_entry)

    mock_req_client.get_virtual_cam_status.side_effect = OBSSDKRequestError("GetVirtualCamStatus", 207)
    await _refresh(hass, mock_config_entry)
    assert not mock_config_entry.runtime_data.coordinator.last_update_success
    assert mock_config_entry.runtime_data.connection.connected

    mock_req_client.get_virtual_cam_status.side_effect = None
    mock_req_client.get_virtual_cam_status.return_value = make_virtual_cam_status(active=True)
    await _refresh(hass, mock_config_entry)
    assert hass.states.get(ENTITY_ID).state == STATE_ON


@pytest.mark.usefixtures("mock_obsws")
async def test_virtual_cam_connection_error_is_not_swallowed(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_req_client: MagicMock
) -> None:
    """Only an OBS request error means "no virtual camera"; a dropped socket still fails the poll."""
    await _setup(hass, mock_config_entry)

    mock_req_client.get_virtual_cam_status.side_effect = ConnectionError("socket closed")
    await _refresh(hass, mock_config_entry)

    assert not mock_config_entry.runtime_data.coordinator.last_update_success
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE

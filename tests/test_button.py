"""Tests for the OBS WebSocket button platform."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.obs_websocket.const import DOMAIN

from .conftest import (
    MOCK_CONFIG,
    MOCK_HOST,
    MOCK_PORT,
    make_event_client_class,
    make_service_settings,
    make_stream_status,
)

START_ENTITY_ID = "button.obs_studio_192_168_1_100_start_stream"
STOP_ENTITY_ID = "button.obs_studio_192_168_1_100_stop_stream"
START_RECORD_ENTITY_ID = "button.obs_studio_192_168_1_100_start_recording"
STOP_RECORD_ENTITY_ID = "button.obs_studio_192_168_1_100_stop_recording"


def _make_mock_obs(req_client: MagicMock) -> MagicMock:
    """Create a mock obsws_python module."""
    mock_obs = MagicMock()
    mock_obs.ReqClient.return_value = req_client
    mock_obs.EventClient = make_event_client_class()
    return mock_obs


def _make_req_client() -> MagicMock:
    """Create a mock ReqClient."""
    client = MagicMock()
    client.get_stream_status.return_value = make_stream_status()
    client.get_stream_service_settings.return_value = make_service_settings()
    client.disconnect.return_value = None
    client.start_stream.return_value = None
    client.stop_stream.return_value = None
    client.start_record.return_value = None
    client.stop_record.return_value = None
    return client


async def _setup_integration(hass: HomeAssistant, req_client: MagicMock) -> MockConfigEntry:
    """Set up integration with given mock client."""
    import sys

    mock_obs = _make_mock_obs(req_client)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=MOCK_HOST,
        data=MOCK_CONFIG.copy(),
        unique_id=f"{MOCK_HOST}:{MOCK_PORT}",
    )
    entry.add_to_hass(hass)

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(sys.modules, "obsws_python", mock_obs)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return entry


async def test_button_entities_registered(hass: HomeAssistant) -> None:
    """Test that button entities are registered."""
    req_client = _make_req_client()
    await _setup_integration(hass, req_client)

    ent_reg = er.async_get(hass)

    start = ent_reg.async_get(START_ENTITY_ID)
    stop = ent_reg.async_get(STOP_ENTITY_ID)

    assert start is not None
    assert stop is not None


async def test_button_unique_ids(hass: HomeAssistant) -> None:
    """Test button unique IDs are correctly set."""
    req_client = _make_req_client()
    entry = await _setup_integration(hass, req_client)

    ent_reg = er.async_get(hass)

    start = ent_reg.async_get(START_ENTITY_ID)
    stop = ent_reg.async_get(STOP_ENTITY_ID)

    assert start.unique_id == f"{entry.entry_id}_start_stream"
    assert stop.unique_id == f"{entry.entry_id}_stop_stream"


async def test_press_start_stream_success(hass: HomeAssistant) -> None:
    """Test pressing start stream button succeeds."""
    req_client = _make_req_client()
    await _setup_integration(hass, req_client)

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": START_ENTITY_ID},
        blocking=True,
    )

    req_client.start_stream.assert_called_once()


async def test_press_stop_stream_success(hass: HomeAssistant) -> None:
    """Test pressing stop stream button succeeds."""
    req_client = _make_req_client()
    await _setup_integration(hass, req_client)

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": STOP_ENTITY_ID},
        blocking=True,
    )

    req_client.stop_stream.assert_called_once()


async def test_press_start_stream_failure(hass: HomeAssistant) -> None:
    """Test pressing start stream button raises error on failure."""
    req_client = _make_req_client()
    await _setup_integration(hass, req_client)

    req_client.start_stream.side_effect = Exception("Stream already active")

    with (
        patch.dict("sys.modules", {"obsws_python": _make_mock_obs(req_client)}),
        pytest.raises(HomeAssistantError) as exc_info,
    ):
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": START_ENTITY_ID},
            blocking=True,
        )

    assert exc_info.value.translation_key == "start_stream_failed"
    assert str(exc_info.value) == f"Failed to start streaming on OBS at {MOCK_HOST}: Stream already active"


async def test_press_stop_stream_failure(hass: HomeAssistant) -> None:
    """Test pressing stop stream button raises error on failure."""
    req_client = _make_req_client()
    await _setup_integration(hass, req_client)

    req_client.stop_stream.side_effect = Exception("Not streaming")

    with (
        patch.dict("sys.modules", {"obsws_python": _make_mock_obs(req_client)}),
        pytest.raises(HomeAssistantError) as exc_info,
    ):
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": STOP_ENTITY_ID},
            blocking=True,
        )

    assert exc_info.value.translation_key == "stop_stream_failed"
    assert str(exc_info.value) == f"Failed to stop streaming on OBS at {MOCK_HOST}: Not streaming"


async def test_button_unavailable_on_coordinator_failure(hass: HomeAssistant) -> None:
    """Test buttons become unavailable when coordinator fails."""
    req_client = _make_req_client()
    entry = await _setup_integration(hass, req_client)

    state = hass.states.get(START_ENTITY_ID)
    assert state is not None
    assert state.state != STATE_UNAVAILABLE

    # Simulate coordinator failure
    req_client.get_stream_status.side_effect = Exception("Connection lost")
    coordinator = entry.runtime_data.coordinator
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(START_ENTITY_ID)
    assert state.state == STATE_UNAVAILABLE


async def test_button_device_info(hass: HomeAssistant) -> None:
    """Test button device info is set correctly."""
    req_client = _make_req_client()
    await _setup_integration(hass, req_client)

    state = hass.states.get(START_ENTITY_ID)
    assert state is not None

    from homeassistant.helpers import device_registry as dr

    dev_registry = dr.async_get(hass)
    ent = er.async_get(hass).async_get(START_ENTITY_ID)
    devices = dr.async_entries_for_config_entry(dev_registry, ent.config_entry_id)
    assert len(devices) >= 1
    assert MOCK_HOST in devices[0].name


@pytest.mark.parametrize(
    ("entity_id", "unique_suffix", "method"),
    [
        (START_RECORD_ENTITY_ID, "start_record", "start_record"),
        (STOP_RECORD_ENTITY_ID, "stop_record", "stop_record"),
    ],
)
async def test_press_record_button_success(
    hass: HomeAssistant, entity_id: str, unique_suffix: str, method: str
) -> None:
    """Test the record buttons are registered and send their request."""
    req_client = _make_req_client()
    entry = await _setup_integration(hass, req_client)

    ent = er.async_get(hass).async_get(entity_id)
    assert ent is not None
    assert ent.unique_id == f"{entry.entry_id}_{unique_suffix}"

    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)

    getattr(req_client, method).assert_called_once()
    req_client.start_stream.assert_not_called()
    req_client.stop_stream.assert_not_called()


@pytest.mark.parametrize(
    ("entity_id", "method", "translation_key", "message"),
    [
        (
            START_RECORD_ENTITY_ID,
            "start_record",
            "start_record_failed",
            f"Failed to start recording on OBS at {MOCK_HOST}: Recording already active",
        ),
        (
            STOP_RECORD_ENTITY_ID,
            "stop_record",
            "stop_record_failed",
            f"Failed to stop recording on OBS at {MOCK_HOST}: Recording already active",
        ),
    ],
)
async def test_press_record_button_failure(
    hass: HomeAssistant, entity_id: str, method: str, translation_key: str, message: str
) -> None:
    """Test the record buttons raise a translated error on failure."""
    req_client = _make_req_client()
    await _setup_integration(hass, req_client)

    getattr(req_client, method).side_effect = Exception("Recording already active")

    with (
        patch.dict("sys.modules", {"obsws_python": _make_mock_obs(req_client)}),
        pytest.raises(HomeAssistantError) as exc_info,
    ):
        await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)

    assert exc_info.value.translation_key == translation_key
    assert str(exc_info.value) == message

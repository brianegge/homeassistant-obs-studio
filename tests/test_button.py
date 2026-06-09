"""Tests for the OBS WebSocket button platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.obs_websocket.const import DOMAIN

from .conftest import MOCK_CONFIG, MOCK_HOST, MOCK_PORT, make_service_settings, make_stream_status

START_ENTITY_ID = "button.obs_studio_192_168_1_100"
STOP_ENTITY_ID = "button.obs_studio_192_168_1_100_2"


def _make_mock_obs(req_client: MagicMock) -> MagicMock:
    """Create a mock obsws_python module."""
    mock_obs = MagicMock()
    mock_obs.ReqClient.return_value = req_client
    mock_obs.EventClient = type("EventClient", (), {"__init__": lambda self, **kw: None})
    return mock_obs


def _make_req_client() -> MagicMock:
    """Create a mock ReqClient."""
    client = MagicMock()
    client.get_stream_status.return_value = make_stream_status()
    client.get_stream_service_settings.return_value = make_service_settings()
    client.disconnect.return_value = None
    client.start_stream.return_value = None
    client.stop_stream.return_value = None
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

    with pytest.raises(HomeAssistantError, match="start_stream_failed"):
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": START_ENTITY_ID},
            blocking=True,
        )


async def test_press_stop_stream_failure(hass: HomeAssistant) -> None:
    """Test pressing stop stream button raises error on failure."""
    req_client = _make_req_client()
    await _setup_integration(hass, req_client)

    req_client.stop_stream.side_effect = Exception("Not streaming")

    with pytest.raises(HomeAssistantError, match="stop_stream_failed"):
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": STOP_ENTITY_ID},
            blocking=True,
        )


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

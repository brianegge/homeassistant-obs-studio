"""Tests for OBS WebSocket diagnostics."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.obs_websocket.const import DOMAIN
from custom_components.obs_websocket.diagnostics import async_get_config_entry_diagnostics

from .conftest import MOCK_CONFIG, MOCK_HOST, MOCK_PORT, make_stream_status, make_service_settings


def _make_mock_obs(req_client: MagicMock) -> MagicMock:
    """Create a mock obsws_python module."""
    mock_obs = MagicMock()
    mock_obs.ReqClient.return_value = req_client
    mock_obs.EventClient = type(
        "EventClient", (), {"__init__": lambda self, **kw: None}
    )
    return mock_obs


def _make_req_client() -> MagicMock:
    """Create a mock ReqClient."""
    client = MagicMock()
    client.get_stream_status.return_value = make_stream_status(active=True)
    client.get_stream_service_settings.return_value = make_service_settings()
    client.disconnect.return_value = None
    return client


async def test_diagnostics(hass: HomeAssistant) -> None:
    """Test diagnostics returns expected structure with redacted fields."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=MOCK_HOST,
        data=MOCK_CONFIG.copy(),
        unique_id=f"{MOCK_HOST}:{MOCK_PORT}",
    )
    entry.add_to_hass(hass)

    req_client = _make_req_client()
    mock_obs = _make_mock_obs(req_client)

    with patch.dict("sys.modules", {"obsws_python": mock_obs}):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, entry)

    # Check structure
    assert "config_entry" in result
    assert "connection" in result
    assert "coordinator" in result

    # Password should be redacted
    assert result["config_entry"]["data"]["password"] == "**REDACTED**"

    # Host should be present
    assert result["config_entry"]["data"]["host"] == MOCK_HOST
    assert result["connection"]["host"] == MOCK_HOST
    assert result["connection"]["connected"] is True

    # Coordinator data
    assert result["coordinator"]["last_update_success"] is True
    assert result["coordinator"]["data"]["stream_status"]["output_active"] is True

    # Stream key should be redacted
    service_settings = result["coordinator"]["data"]["service_settings"]["stream_service_settings"]
    assert service_settings["key"] == "**REDACTED**"
    assert service_settings["server"] == "rtmp://live.twitch.tv/app"


async def test_diagnostics_no_data(hass: HomeAssistant) -> None:
    """Test diagnostics when coordinator has no data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=MOCK_HOST,
        data=MOCK_CONFIG.copy(),
        unique_id=f"{MOCK_HOST}:{MOCK_PORT}",
    )
    entry.add_to_hass(hass)

    req_client = _make_req_client()
    mock_obs = _make_mock_obs(req_client)

    with patch.dict("sys.modules", {"obsws_python": mock_obs}):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Force coordinator data to None
    entry.runtime_data.coordinator.data = None

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["coordinator"]["data"] == {}

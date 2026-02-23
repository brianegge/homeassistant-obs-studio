"""Shared fixtures for OBS WebSocket tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import loader

from custom_components.obs_websocket.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(hass: HomeAssistant) -> None:
    """Enable custom integrations in all tests."""
    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS)

MOCK_HOST = "192.168.1.100"
MOCK_PORT = 4455
MOCK_PASSWORD = "testpass"

MOCK_CONFIG = {
    "host": MOCK_HOST,
    "port": MOCK_PORT,
    "password": MOCK_PASSWORD,
}


def make_stream_status(
    *,
    active: bool = False,
    reconnecting: bool = False,
    output_bytes: int = 0,
    output_duration: int = 0,
    output_timecode: str = "00:00:00.000",
    output_skipped_frames: int = 0,
    output_total_frames: int = 0,
    output_congestion: float = 0.0,
) -> SimpleNamespace:
    """Create a mock stream status response."""
    return SimpleNamespace(
        output_active=active,
        output_reconnecting=reconnecting,
        output_bytes=output_bytes,
        output_duration=output_duration,
        output_timecode=output_timecode,
        output_skipped_frames=output_skipped_frames,
        output_total_frames=output_total_frames,
        output_congestion=output_congestion,
    )


def make_service_settings(
    *,
    service_type: str = "rtmp_common",
    settings: dict | None = None,
) -> SimpleNamespace:
    """Create a mock service settings response."""
    return SimpleNamespace(
        stream_service_type=service_type,
        stream_service_settings=settings
        or {"server": "rtmp://live.twitch.tv/app", "key": "live_abc123"},
    )


@pytest.fixture
def mock_config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create and add a mock config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=MOCK_HOST,
        data=MOCK_CONFIG.copy(),
        unique_id=f"{MOCK_HOST}:{MOCK_PORT}",
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_req_client() -> MagicMock:
    """Create a mock ReqClient."""
    client = MagicMock()
    client.get_version.return_value = SimpleNamespace(obs_version="30.0.0")
    client.get_stream_status.return_value = make_stream_status()
    client.get_stream_service_settings.return_value = make_service_settings()
    client.disconnect.return_value = None
    return client


@pytest.fixture
def mock_obsws(mock_req_client: MagicMock):
    """Patch obsws_python with mock clients."""
    mock_obs = MagicMock()
    mock_obs.ReqClient.return_value = mock_req_client
    # EventClient is subclassed, so provide a base class
    mock_obs.EventClient = type(
        "EventClient", (), {"__init__": lambda self, **kw: None}
    )

    with patch.dict("sys.modules", {"obsws_python": mock_obs}):
        yield mock_obs

"""Shared fixtures for OBS WebSocket tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from homeassistant import loader
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.obs_websocket.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(hass: HomeAssistant) -> None:
    """Enable custom integrations in all tests."""
    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS)


MOCK_HOST = "192.168.1.100"
MOCK_PORT = 4455
MOCK_PASSWORD = "mock-password-for-testing"  # NOSONAR
MOCK_NEW_PASSWORD = "mock-new-password"  # NOSONAR
MOCK_WRONG_PASSWORD = "mock-wrong-password"  # NOSONAR

MOCK_CONFIG = {
    "host": MOCK_HOST,
    "port": MOCK_PORT,
    "password": MOCK_PASSWORD,
}


class OBSSDKError(Exception):
    """Stand-in for obsws_python.error.OBSSDKError (matched by class name)."""


# The error obsws-python raises when OBS closes the socket because the password is wrong.
WRONG_PASSWORD_ERROR = OBSSDKError("failed to identify client with the server, please check connection settings")


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


def make_record_status(
    *,
    active: bool = False,
    paused: bool = False,
    output_bytes: int = 0,
    output_duration: int = 0,
    output_timecode: str = "00:00:00.000",
) -> SimpleNamespace:
    """Create a mock record status response."""
    return SimpleNamespace(
        output_active=active,
        output_paused=paused,
        output_bytes=output_bytes,
        output_duration=output_duration,
        output_timecode=output_timecode,
    )


def make_stats(
    *,
    active_fps: float = 30.0,
    render_skipped_frames: int = 0,
    render_total_frames: int = 1000,
    output_skipped_frames: int = 0,
    output_total_frames: int = 1000,
    available_disk_space: float = 102400.0,
    cpu_usage: float = 5.0,
    memory_usage: float = 512.0,
    average_frame_render_time: float = 1.5,
) -> SimpleNamespace:
    """Create a mock GetStats response."""
    return SimpleNamespace(
        active_fps=active_fps,
        render_skipped_frames=render_skipped_frames,
        render_total_frames=render_total_frames,
        output_skipped_frames=output_skipped_frames,
        output_total_frames=output_total_frames,
        available_disk_space=available_disk_space,
        cpu_usage=cpu_usage,
        memory_usage=memory_usage,
        average_frame_render_time=average_frame_render_time,
    )


def make_service_settings(
    *,
    service_type: str = "rtmp_common",
    settings: dict | None = None,
) -> SimpleNamespace:
    """Create a mock service settings response."""
    return SimpleNamespace(
        stream_service_type=service_type,
        stream_service_settings=settings or {"server": "rtmp://live.twitch.tv/app", "key": "live_abc123"},
    )


def make_scene_list(names: list[str], *, current: str | None = None) -> SimpleNamespace:
    """Create a mock GetSceneList response, `names` in Scenes dock order (top first).

    Like OBS, the response lists scenes bottom first, with sceneIndex 0 for the last.
    """
    count = len(names)
    scenes = [
        {"sceneIndex": count - 1 - i, "sceneName": name, "sceneUuid": f"uuid-{i}"} for i, name in enumerate(names)
    ]
    return SimpleNamespace(
        current_program_scene_name=current if current is not None else (names[0] if names else None),
        current_preview_scene_name=None,
        scenes=list(reversed(scenes)),
    )


def make_virtual_cam_status(*, active: bool = False) -> SimpleNamespace:
    """Create a mock GetVirtualCamStatus response."""
    return SimpleNamespace(output_active=active)


class OBSSDKRequestError(Exception):
    """Stand-in for obsws_python.error.OBSSDKRequestError (matched by class name)."""

    def __init__(self, req_name: str, code: int, comment: str | None = None) -> None:
        self.req_name = req_name
        self.code = code
        message = f"Request {req_name} returned code {code}."
        if comment:
            message += f" With message: {comment}"
        super().__init__(message)


# What OBS answers GetVirtualCamStatus with when it has no virtual camera.
NO_VIRTUAL_CAM_ERROR = OBSSDKRequestError("GetVirtualCamStatus", 604, "VirtualCam is not available.")


def make_event_client_class() -> type:
    """Create a stand-in for obsws_python.EventClient, which the integration subclasses."""

    def _init(self, **kwargs) -> None:
        # obsws-python only dispatches events to functions registered via callback.register()
        self.callback = MagicMock()

    return type("EventClient", (), {"__init__": _init})


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
    client.get_record_status.return_value = make_record_status()
    client.get_stream_service_settings.return_value = make_service_settings()
    client.get_stats.return_value = make_stats()
    client.get_scene_list.return_value = make_scene_list(["Starting", "Live", "BRB"], current="Live")
    client.get_virtual_cam_status.return_value = make_virtual_cam_status()
    client.disconnect.return_value = None
    return client


@pytest.fixture
def mock_obsws(mock_req_client: MagicMock):
    """Patch obsws_python with mock clients."""
    mock_obs = MagicMock()
    mock_obs.ReqClient.return_value = mock_req_client
    # EventClient is subclassed, so provide a base class
    mock_obs.EventClient = make_event_client_class()

    with patch.dict("sys.modules", {"obsws_python": mock_obs}):
        yield mock_obs

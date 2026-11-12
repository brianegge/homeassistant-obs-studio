"""Tests for the OBS statistics sensors, rate tracking, program camera and request lock."""

from __future__ import annotations

import asyncio
import base64
import threading
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components.camera import async_get_image
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.obs_websocket import OBSRateTracker, screenshot_size
from custom_components.obs_websocket.const import DOMAIN, MIN_RATE_INTERVAL

from .conftest import (
    MOCK_CONFIG,
    MOCK_HOST,
    MOCK_PORT,
    make_event_client_class,
    make_record_status,
    make_service_settings,
    make_stats,
    make_stream_status,
)

PREFIX = "obs_studio_192_168_1_100"
CAMERA_ENTITY_ID = f"camera.{PREFIX}_program"
JPEG = b"\xff\xd8\xff\xe0fake-jpeg\xff\xd9"


def _req_client(**stream: Any) -> MagicMock:
    client = MagicMock()
    client.get_stream_status.return_value = make_stream_status(**stream)
    client.get_record_status.return_value = make_record_status()
    client.get_stream_service_settings.return_value = make_service_settings()
    client.get_stats.return_value = make_stats(
        active_fps=20.3,
        render_skipped_frames=470,
        render_total_frames=1000,
        available_disk_space=97338.4,
    )
    client.get_current_program_scene.return_value = SimpleNamespace(scene_name="Scene")
    client.get_video_settings.return_value = SimpleNamespace(base_width=1920, base_height=1080)
    client.get_source_screenshot.return_value = SimpleNamespace(
        image_data="data:image/jpg;base64," + base64.b64encode(JPEG).decode()
    )
    client.disconnect.return_value = None
    return client


async def _setup(hass: HomeAssistant, client: MagicMock, *, enable: tuple[str, ...] = ()) -> MockConfigEntry:
    mock_obs = MagicMock()
    mock_obs.ReqClient.return_value = client
    mock_obs.EventClient = make_event_client_class()
    entry = MockConfigEntry(
        domain=DOMAIN, title=MOCK_HOST, data=MOCK_CONFIG.copy(), unique_id=f"{MOCK_HOST}:{MOCK_PORT}"
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    for entity_id in enable:
        domain, object_id = entity_id.split(".")
        key = object_id.removeprefix(f"{PREFIX}_")
        registry.async_get_or_create(
            domain, DOMAIN, f"{entry.entry_id}_{key}", suggested_object_id=object_id, config_entry=entry
        )
    with patch.dict("sys.modules", {"obsws_python": mock_obs}):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def _sample(
    *,
    streaming: bool = True,
    stream_bytes: int = 0,
    stream_skipped: int = 0,
    stream_total: int = 0,
    render_skipped: int = 0,
    render_total: int = 0,
    lag_skipped: int = 0,
    lag_total: int = 0,
) -> dict[str, Any]:
    return {
        "stream_status": make_stream_status(
            active=streaming,
            output_bytes=stream_bytes,
            output_skipped_frames=stream_skipped,
            output_total_frames=stream_total,
        ),
        "stats": make_stats(
            render_skipped_frames=render_skipped,
            render_total_frames=render_total,
            output_skipped_frames=lag_skipped,
            output_total_frames=lag_total,
        ),
    }


# --- Rate tracking ---------------------------------------------------------


def test_first_sample_measures_since_start() -> None:
    """With no baseline yet, the percentages cover the counters since they started."""
    rates = OBSRateTracker().update(_sample(render_skipped=470, render_total=1000, stream_total=10), 100.0)
    assert rates["render_skipped_pct"] == 47.0
    assert rates["stream_dropped_pct"] == 0.0
    assert rates["stream_bitrate"] is None  # needs two samples


def test_rates_cover_only_the_last_window() -> None:
    """A past burst of skipped frames does not keep the percentage high."""
    tracker = OBSRateTracker()
    tracker.update(_sample(stream_bytes=0, render_skipped=470, render_total=1000, stream_total=100), 100.0)
    rates = tracker.update(
        _sample(stream_bytes=7_500_000, render_skipped=476, render_total=1600, stream_skipped=6, stream_total=700),
        160.0,
    )
    assert rates["render_skipped_pct"] == 1.0  # 6 of 600, not 476 of 1600
    assert rates["stream_dropped_pct"] == 1.0
    assert rates["stream_bitrate"] == 1000  # 7.5 MB in 60 s = 1000 kbit/s


def test_short_window_keeps_previous_rates() -> None:
    """An event refresh right after a poll does not compute a noisy ratio."""
    tracker = OBSRateTracker()
    tracker.update(_sample(render_total=1000), 100.0)
    first = tracker.update(_sample(render_skipped=30, render_total=1600), 160.0)
    again = tracker.update(_sample(render_skipped=40, render_total=1601), 160.0 + MIN_RATE_INTERVAL / 2)
    assert again == first


def test_counter_reset_measures_from_zero() -> None:
    """A new stream restarts OBS's per-output counters; that is not a negative rate."""
    tracker = OBSRateTracker()
    tracker.update(_sample(stream_bytes=9_000_000, stream_skipped=50, stream_total=5000), 100.0)
    rates = tracker.update(_sample(stream_bytes=100_000, stream_skipped=3, stream_total=300), 160.0)
    assert rates["stream_dropped_pct"] == 1.0
    assert rates["stream_bitrate"] is None


def test_not_streaming() -> None:
    """Idle: bitrate is zero and there is no dropped-frame percentage."""
    tracker = OBSRateTracker()
    tracker.update(_sample(streaming=False, render_total=1000), 100.0)
    rates = tracker.update(_sample(streaming=False, render_total=1600), 160.0)
    assert rates["stream_bitrate"] == 0
    assert rates["stream_dropped_pct"] is None
    assert rates["encoding_lag_pct"] is None  # no frames encoded in the window


def test_missing_stats_fields() -> None:
    """A response without the counters gives unknown values, not an exception."""
    rates = OBSRateTracker().update({"stream_status": None, "stats": SimpleNamespace()}, 100.0)
    assert rates["render_skipped_pct"] is None
    assert rates["stream_bitrate"] == 0


# --- Sensors ---------------------------------------------------------------


async def test_stat_sensors(hass: HomeAssistant) -> None:
    """The enabled-by-default stat sensors report GetStats and the derived rates."""
    await _setup(hass, _req_client())

    assert float(hass.states.get(f"sensor.{PREFIX}_active_fps").state) == pytest.approx(20.3)

    render = hass.states.get(f"sensor.{PREFIX}_render_skipped_frames")
    assert float(render.state) == 47.0
    assert render.attributes["skipped_frames"] == 470
    assert render.attributes["total_frames"] == 1000
    assert render.attributes["unit_of_measurement"] == "%"

    disk = hass.states.get(f"sensor.{PREFIX}_available_disk_space")
    assert disk.attributes["unit_of_measurement"] == "GB"
    assert float(disk.state) == pytest.approx(97.3384, abs=0.001)

    assert hass.states.get(f"sensor.{PREFIX}_stream_bitrate").state == "0"
    assert hass.states.get(f"sensor.{PREFIX}_stream_congestion").state == STATE_UNKNOWN
    assert hass.states.get(f"sensor.{PREFIX}_stream_dropped_frames").state == STATE_UNKNOWN


async def test_congestion_while_streaming(hass: HomeAssistant) -> None:
    """Congestion is reported as a percentage while the stream is live."""
    await _setup(hass, _req_client(active=True, output_congestion=0.125, output_total_frames=100))
    assert float(hass.states.get(f"sensor.{PREFIX}_stream_congestion").state) == 12.5
    assert float(hass.states.get(f"sensor.{PREFIX}_stream_dropped_frames").state) == 0.0


async def test_diagnostic_stat_sensors_disabled_by_default(hass: HomeAssistant) -> None:
    """CPU, memory and render time are diagnostic and start disabled."""
    await _setup(hass, _req_client())
    registry = er.async_get(hass)
    for key in ("cpu_usage", "memory_usage", "average_frame_render_time"):
        entity = registry.async_get(f"sensor.{PREFIX}_{key}")
        assert entity is not None, key
        assert entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert entity.entity_category == "diagnostic"


async def test_diagnostic_stat_sensors_when_enabled(hass: HomeAssistant) -> None:
    """Enabled diagnostic sensors report their values."""
    await _setup(
        hass,
        _req_client(),
        enable=(f"sensor.{PREFIX}_cpu_usage", f"sensor.{PREFIX}_average_frame_render_time"),
    )
    assert float(hass.states.get(f"sensor.{PREFIX}_cpu_usage").state) == 5.0
    assert float(hass.states.get(f"sensor.{PREFIX}_average_frame_render_time").state) == 1.5


# --- Program camera --------------------------------------------------------


async def test_camera_disabled_by_default(hass: HomeAssistant) -> None:
    """Screenshots cost OBS GPU time, so the camera starts disabled."""
    await _setup(hass, _req_client())
    entity = er.async_get(hass).async_get(CAMERA_ENTITY_ID)
    assert entity is not None
    assert entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_camera_image(hass: HomeAssistant) -> None:
    """The camera returns a decoded JPEG of the current program scene."""
    client = _req_client()
    await _setup(hass, client, enable=(CAMERA_ENTITY_ID,))

    image = await async_get_image(hass, CAMERA_ENTITY_ID)

    assert image.content == JPEG
    assert image.content_type == "image/jpeg"
    # 16:9 canvas: the long side is the requested size and the aspect is kept.
    client.get_source_screenshot.assert_called_once_with("Scene", "jpg", 1280, 720, 80)


async def test_camera_image_size_is_clamped(hass: HomeAssistant) -> None:
    """A requested size outside OBS's 8-4096 range is clamped."""
    client = _req_client()
    entry = await _setup(hass, client, enable=(CAMERA_ENTITY_ID,))
    camera = hass.data["camera"].get_entity(CAMERA_ENTITY_ID)
    assert entry.state.value == "loaded"

    await camera.async_camera_image(width=10000)
    assert client.get_source_screenshot.call_args.args[2:4] == (4096, 2304)
    await camera.async_camera_image(width=2, height=3)
    assert client.get_source_screenshot.call_args.args[2:4] == (8, 8)


@pytest.mark.parametrize(
    ("canvas", "size", "expected"),
    [
        ((1920, 1080), 640, (640, 360)),
        ((1080, 1920), 640, (360, 640)),  # portrait canvas
        ((1920, 1080), 8, (8, 8)),  # the short side would be under OBS's minimum
    ],
)
def test_screenshot_size(canvas: tuple[int, int], size: int, expected: tuple[int, int]) -> None:
    """Screenshots keep the canvas aspect ratio."""
    assert screenshot_size(*canvas, size) == expected


async def test_camera_image_failure(hass: HomeAssistant) -> None:
    """A failed screenshot yields no image rather than an exception from the entity."""
    client = _req_client()
    await _setup(hass, client, enable=(CAMERA_ENTITY_ID,))
    client.get_source_screenshot.side_effect = Exception("source not found")

    camera = hass.data["camera"].get_entity(CAMERA_ENTITY_ID)
    assert await camera.async_camera_image() is None
    with pytest.raises(HomeAssistantError):
        await async_get_image(hass, CAMERA_ENTITY_ID)


# --- Request serialization -------------------------------------------------


async def test_requests_are_serialized(hass: HomeAssistant) -> None:
    """Two requests never share the socket at once (obsws-python can't match replies)."""
    client = _req_client()
    entry = await _setup(hass, client)
    connection = entry.runtime_data.connection

    active = 0
    peak = 0
    guard = threading.Lock()

    def slow(_client: Any) -> None:
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with guard:
            active -= 1

    await asyncio.gather(*(connection._async_request(slow) for _ in range(4)))
    assert peak == 1

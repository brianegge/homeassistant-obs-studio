"""Tests for OBS WebSocket sensor platform."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from homeassistant.const import EntityCategory, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.obs_websocket.const import DOMAIN
from custom_components.obs_websocket.sensor import OBSStreamStatusSensor, OBSStreamServiceSensor

from .conftest import MOCK_CONFIG, MOCK_HOST, MOCK_PORT, make_stream_status, make_service_settings


def _make_mock_obs(req_client: MagicMock) -> MagicMock:
    """Create a mock obsws_python module."""
    mock_obs = MagicMock()
    mock_obs.ReqClient.return_value = req_client
    mock_obs.EventClient = type(
        "EventClient", (), {"__init__": lambda self, **kw: None}
    )
    return mock_obs


def _make_req_client(
    *,
    active: bool = False,
    reconnecting: bool = False,
    output_bytes: int = 0,
    output_duration: int = 0,
    output_timecode: str = "00:00:00.000",
    output_skipped_frames: int = 0,
    output_total_frames: int = 0,
    output_congestion: float = 0.0,
    service_type: str = "rtmp_common",
    service_settings: dict | None = None,
) -> MagicMock:
    """Create a mock ReqClient with configurable state."""
    client = MagicMock()
    client.get_stream_status.return_value = make_stream_status(
        active=active,
        reconnecting=reconnecting,
        output_bytes=output_bytes,
        output_duration=output_duration,
        output_timecode=output_timecode,
        output_skipped_frames=output_skipped_frames,
        output_total_frames=output_total_frames,
        output_congestion=output_congestion,
    )
    client.get_stream_service_settings.return_value = make_service_settings(
        service_type=service_type,
        settings=service_settings,
    )
    client.disconnect.return_value = None
    return client


async def _setup_integration(
    hass: HomeAssistant, req_client: MagicMock
) -> MockConfigEntry:
    """Set up the integration with a mock client."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=MOCK_HOST,
        data=MOCK_CONFIG.copy(),
        unique_id=f"{MOCK_HOST}:{MOCK_PORT}",
    )
    entry.add_to_hass(hass)

    mock_obs = _make_mock_obs(req_client)

    with patch.dict("sys.modules", {"obsws_python": mock_obs}):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return entry


async def test_stream_status_idle(hass: HomeAssistant) -> None:
    """Test stream status sensor shows idle when not streaming."""
    req_client = _make_req_client(active=False)
    await _setup_integration(hass, req_client)

    state = hass.states.get("sensor.obs_studio_192_168_1_100_none")
    assert state is not None
    assert state.state == "idle"


async def test_stream_status_streaming(hass: HomeAssistant) -> None:
    """Test stream status sensor shows streaming when active."""
    req_client = _make_req_client(
        active=True,
        output_bytes=1024000,
        output_duration=60000,
        output_timecode="00:01:00.000",
        output_skipped_frames=5,
        output_total_frames=3600,
        output_congestion=0.1,
    )
    await _setup_integration(hass, req_client)

    state = hass.states.get("sensor.obs_studio_192_168_1_100_none")
    assert state is not None
    assert state.state == "streaming"
    assert state.attributes["output_bytes"] == 1024000
    assert state.attributes["output_duration"] == 60000
    assert state.attributes["output_timecode"] == "00:01:00.000"
    assert state.attributes["output_skipped_frames"] == 5
    assert state.attributes["output_total_frames"] == 3600
    assert state.attributes["output_congestion"] == 0.1


async def test_stream_status_reconnecting(hass: HomeAssistant) -> None:
    """Test stream status sensor shows reconnecting."""
    req_client = _make_req_client(active=True, reconnecting=True)
    await _setup_integration(hass, req_client)

    state = hass.states.get("sensor.obs_studio_192_168_1_100_none")
    assert state is not None
    assert state.state == "reconnecting"


async def test_stream_service_sensor(hass: HomeAssistant) -> None:
    """Test stream service sensor shows service type and settings."""
    settings = {"server": "rtmp://live.twitch.tv/app", "key": "live_key123"}
    req_client = _make_req_client(
        service_type="rtmp_common",
        service_settings=settings,
    )
    await _setup_integration(hass, req_client)

    state = hass.states.get("sensor.obs_studio_192_168_1_100_none_2")
    assert state is not None
    assert state.state == "rtmp_common"
    assert state.attributes["stream_service_settings"] == settings


async def test_sensors_unavailable_on_connection_failure(
    hass: HomeAssistant,
) -> None:
    """Test sensors become unavailable when connection drops."""
    req_client = _make_req_client(active=True)
    entry = await _setup_integration(hass, req_client)

    state = hass.states.get("sensor.obs_studio_192_168_1_100_none")
    assert state.state == "streaming"

    # Simulate connection failure
    req_client.get_stream_status.side_effect = ConnectionError("Lost")

    coordinator = entry.runtime_data.coordinator
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get("sensor.obs_studio_192_168_1_100_none")
    assert state.state == STATE_UNAVAILABLE

    state = hass.states.get("sensor.obs_studio_192_168_1_100_none_2")
    assert state.state == STATE_UNAVAILABLE


async def test_two_sensors_created(hass: HomeAssistant) -> None:
    """Test that both sensors are created."""
    req_client = _make_req_client()
    await _setup_integration(hass, req_client)

    status = hass.states.get("sensor.obs_studio_192_168_1_100_none")
    service = hass.states.get("sensor.obs_studio_192_168_1_100_none_2")

    assert status is not None
    assert service is not None


async def test_stream_status_attributes_when_idle(hass: HomeAssistant) -> None:
    """Test stream status attributes are present when idle."""
    req_client = _make_req_client(active=False)
    await _setup_integration(hass, req_client)

    state = hass.states.get("sensor.obs_studio_192_168_1_100_none")
    assert state.state == "idle"
    assert "output_bytes" in state.attributes
    assert "output_timecode" in state.attributes


async def test_sensor_native_value_none_when_no_data(
    hass: HomeAssistant,
) -> None:
    """Test sensors return None when coordinator data is None."""
    req_client = _make_req_client()
    entry = await _setup_integration(hass, req_client)

    coordinator = entry.runtime_data.coordinator

    # Directly test sensor methods with None data
    status_sensor = OBSStreamStatusSensor(coordinator, entry)
    service_sensor = OBSStreamServiceSensor(coordinator, entry)

    # Force coordinator data to None
    coordinator.data = None

    assert status_sensor.native_value is None
    assert status_sensor.extra_state_attributes == {}
    assert service_sensor.native_value is None
    assert service_sensor.extra_state_attributes == {}


async def test_service_sensor_entity_category(hass: HomeAssistant) -> None:
    """Test stream service sensor has diagnostic entity category."""
    req_client = _make_req_client()
    await _setup_integration(hass, req_client)

    ent_reg = er.async_get(hass)
    entity = ent_reg.async_get("sensor.obs_studio_192_168_1_100_none_2")
    assert entity is not None
    assert entity.entity_category == EntityCategory.DIAGNOSTIC

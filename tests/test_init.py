"""Tests for OBS WebSocket integration setup and coordinator."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.obs_websocket import OBSRuntimeData
from custom_components.obs_websocket.const import DOMAIN

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
) -> MagicMock:
    """Create a mock ReqClient with configurable state."""
    client = MagicMock()
    client.get_stream_status.return_value = make_stream_status(
        active=active, reconnecting=reconnecting
    )
    client.get_stream_service_settings.return_value = make_service_settings()
    client.disconnect.return_value = None
    return client


async def test_setup_entry(hass: HomeAssistant) -> None:
    """Test successful setup of a config entry."""
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

    assert entry.state is ConfigEntryState.LOADED
    assert isinstance(entry.runtime_data, OBSRuntimeData)
    assert entry.runtime_data.connection.host == MOCK_HOST
    assert entry.runtime_data.coordinator is not None


async def test_setup_entry_connection_failure(hass: HomeAssistant) -> None:
    """Test setup fails when OBS is unreachable."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=MOCK_HOST,
        data=MOCK_CONFIG.copy(),
        unique_id=f"{MOCK_HOST}:{MOCK_PORT}",
    )
    entry.add_to_hass(hass)

    mock_obs = MagicMock()
    mock_obs.ReqClient.side_effect = ConnectionRefusedError("Connection refused")
    mock_obs.EventClient = type(
        "EventClient", (), {"__init__": lambda self, **kw: None}
    )

    with patch.dict("sys.modules", {"obsws_python": mock_obs}):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload_entry(hass: HomeAssistant) -> None:
    """Test successful unload of a config entry."""
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

        assert entry.state is ConfigEntryState.LOADED

        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_coordinator_update_success(hass: HomeAssistant) -> None:
    """Test coordinator successfully fetches data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=MOCK_HOST,
        data=MOCK_CONFIG.copy(),
        unique_id=f"{MOCK_HOST}:{MOCK_PORT}",
    )
    entry.add_to_hass(hass)

    req_client = _make_req_client(active=True)
    mock_obs = _make_mock_obs(req_client)

    with patch.dict("sys.modules", {"obsws_python": mock_obs}):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinator
    assert coordinator.data is not None
    assert coordinator.data["stream_status"].output_active is True


async def test_coordinator_update_failure_logs_warning(
    hass: HomeAssistant, caplog
) -> None:
    """Test coordinator logs warning when connection drops."""
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

        # Now make the next fetch fail
        req_client.get_stream_status.side_effect = ConnectionError("Lost connection")

        coordinator = entry.runtime_data.coordinator
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    assert "is unavailable" in caplog.text


async def test_coordinator_recovery_logs_info(
    hass: HomeAssistant, caplog
) -> None:
    """Test coordinator logs info when connection recovers."""
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

        # Make it fail
        req_client.get_stream_status.side_effect = ConnectionError("Lost")
        coordinator = entry.runtime_data.coordinator
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # Now recover
        req_client.get_stream_status.side_effect = None
        req_client.get_stream_status.return_value = make_stream_status()
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    assert "is available again" in caplog.text


async def test_setup_no_password(hass: HomeAssistant) -> None:
    """Test setup with no password."""
    config_no_pass = {"host": MOCK_HOST, "port": MOCK_PORT, "password": ""}
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=MOCK_HOST,
        data=config_no_pass,
        unique_id=f"{MOCK_HOST}:{MOCK_PORT}",
    )
    entry.add_to_hass(hass)

    req_client = _make_req_client()
    mock_obs = _make_mock_obs(req_client)

    with patch.dict("sys.modules", {"obsws_python": mock_obs}):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED


async def test_on_event_triggers_refresh(hass: HomeAssistant) -> None:
    """Test that _on_event triggers a coordinator refresh."""
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

        connection = entry.runtime_data.connection

        # Update the mock to return streaming state
        req_client.get_stream_status.return_value = make_stream_status(active=True)

        # Simulate an event callback from OBS (normally called from EventClient thread)
        # Call from executor to mimic real behavior
        await hass.async_add_executor_job(connection._on_event)
        await hass.async_block_till_done()

        # Coordinator should have refreshed with new data
        coordinator = entry.runtime_data.coordinator
        assert coordinator.data["stream_status"].output_active is True


async def test_on_event_no_coordinator(hass: HomeAssistant) -> None:
    """Test that _on_event is safe when coordinator is None."""
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

    connection = entry.runtime_data.connection
    connection.coordinator = None

    # Should not raise
    connection._on_event()


async def test_coordinator_reconnects_after_disconnect(
    hass: HomeAssistant,
) -> None:
    """Test coordinator reconnects when connection was lost."""
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

        connection = entry.runtime_data.connection

        # Simulate disconnect
        await connection.async_disconnect()
        assert not connection.connected

        # Next refresh should reconnect
        await entry.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()

        assert connection.connected

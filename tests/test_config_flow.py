"""Tests for OBS WebSocket config flow."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.obs_websocket.const import DOMAIN

from .conftest import MOCK_CONFIG, MOCK_HOST, MOCK_PORT, MOCK_PASSWORD


async def test_user_flow_shows_form(hass: HomeAssistant) -> None:
    """Test that the user flow shows a form initially."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


async def test_user_flow_success(hass: HomeAssistant) -> None:
    """Test successful user config flow creates entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.obs_websocket.config_flow._test_connection",
    ) as mock_test:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=MOCK_CONFIG,
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == MOCK_HOST
    assert result["data"] == MOCK_CONFIG
    mock_test.assert_called_once_with(hass, MOCK_HOST, MOCK_PORT, MOCK_PASSWORD)


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    """Test user config flow with connection failure shows error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.obs_websocket.config_flow._test_connection",
        side_effect=ConnectionRefusedError("Connection refused"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=MOCK_CONFIG,
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_already_configured(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test user flow aborts when already configured."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.obs_websocket.config_flow._test_connection",
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=MOCK_CONFIG,
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow_success(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test successful reauth flow updates password."""
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with patch(
        "custom_components.obs_websocket.config_flow._test_connection",
    ) as mock_test:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"password": "newpass"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data["password"] == "newpass"
    mock_test.assert_called_once_with(hass, MOCK_HOST, MOCK_PORT, "newpass")


async def test_reauth_flow_cannot_connect(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test reauth flow with connection failure shows error."""
    result = await mock_config_entry.start_reauth_flow(hass)

    with patch(
        "custom_components.obs_websocket.config_flow._test_connection",
        side_effect=ConnectionRefusedError("Connection refused"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"password": "wrongpass"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reconfigure_flow_success(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test successful reconfigure flow updates all fields."""
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    new_config = {"host": "10.0.0.50", "port": 4456, "password": "newpass"}

    with patch(
        "custom_components.obs_websocket.config_flow._test_connection",
    ) as mock_test:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=new_config,
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data["host"] == "10.0.0.50"
    assert mock_config_entry.data["port"] == 4456
    assert mock_config_entry.data["password"] == "newpass"
    mock_test.assert_called_once_with(hass, "10.0.0.50", 4456, "newpass")


async def test_reconfigure_flow_cannot_connect(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test reconfigure flow with connection failure shows error."""
    result = await mock_config_entry.start_reconfigure_flow(hass)

    with patch(
        "custom_components.obs_websocket.config_flow._test_connection",
        side_effect=ConnectionRefusedError("Connection refused"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"host": "badhost", "port": 4455, "password": ""},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_no_password(hass: HomeAssistant) -> None:
    """Test user flow without password."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    config_no_pass = {"host": MOCK_HOST, "port": MOCK_PORT, "password": ""}

    with patch(
        "custom_components.obs_websocket.config_flow._test_connection",
    ) as mock_test:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=config_no_pass,
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["password"] == ""
    mock_test.assert_called_once_with(hass, MOCK_HOST, MOCK_PORT, "")


async def test_test_connection_with_password(hass: HomeAssistant) -> None:
    """Test _test_connection exercises obsws_python with password."""
    mock_client = MagicMock()
    mock_client.get_version.return_value = SimpleNamespace(obs_version="30.0.0")
    mock_obs = MagicMock()
    mock_obs.ReqClient.return_value = mock_client

    with patch.dict("sys.modules", {"obsws_python": mock_obs}):
        from custom_components.obs_websocket.config_flow import _test_connection

        await _test_connection(hass, MOCK_HOST, MOCK_PORT, MOCK_PASSWORD)

    mock_obs.ReqClient.assert_called_once_with(
        host=MOCK_HOST, port=MOCK_PORT, timeout=5, password=MOCK_PASSWORD
    )
    mock_client.get_version.assert_called_once()
    mock_client.disconnect.assert_called_once()


async def test_test_connection_without_password(hass: HomeAssistant) -> None:
    """Test _test_connection exercises obsws_python without password."""
    mock_client = MagicMock()
    mock_client.get_version.return_value = SimpleNamespace(obs_version="30.0.0")
    mock_obs = MagicMock()
    mock_obs.ReqClient.return_value = mock_client

    with patch.dict("sys.modules", {"obsws_python": mock_obs}):
        from custom_components.obs_websocket.config_flow import _test_connection

        await _test_connection(hass, MOCK_HOST, MOCK_PORT, "")

    mock_obs.ReqClient.assert_called_once_with(
        host=MOCK_HOST, port=MOCK_PORT, timeout=5
    )


async def test_test_connection_failure(hass: HomeAssistant) -> None:
    """Test _test_connection raises when OBS is unreachable."""
    mock_obs = MagicMock()
    mock_obs.ReqClient.side_effect = ConnectionRefusedError("Connection refused")

    with patch.dict("sys.modules", {"obsws_python": mock_obs}):
        from custom_components.obs_websocket.config_flow import _test_connection

        try:
            await _test_connection(hass, MOCK_HOST, MOCK_PORT, MOCK_PASSWORD)
            assert False, "Should have raised"
        except ConnectionRefusedError:
            pass

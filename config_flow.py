"""Config flow for OBS WebSocket."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant

from .const import DEFAULT_HOST, DEFAULT_PORT, DOMAIN


async def _test_connection(hass: HomeAssistant, host: str, port: int, password: str) -> None:
    """Test that we can connect to OBS WebSocket. Raises on failure."""
    import obsws_python as obs

    def _connect():
        kwargs = {"host": host, "port": port, "timeout": 5}
        if password:
            kwargs["password"] = password
        client = obs.ReqClient(**kwargs)
        client.get_version()
        client.disconnect()

    await hass.async_add_executor_job(_connect)


class OBSWebSocketConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OBS WebSocket."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input["host"]
            port = user_input["port"]
            password = user_input.get("password", "")

            try:
                await _test_connection(self.hass, host, port, password)
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"{host}:{port}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=host,
                    data={"host": host, "port": port, "password": password},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("host", default=DEFAULT_HOST): str,
                    vol.Required("port", default=DEFAULT_PORT): int,
                    vol.Optional("password", default=""): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauthorization when password changes."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauth confirmation."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            password = user_input.get("password", "")
            try:
                await _test_connection(
                    self.hass,
                    reauth_entry.data["host"],
                    reauth_entry.data["port"],
                    password,
                )
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data={**reauth_entry.data, "password": password},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional("password", default=""): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration."""
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            host = user_input["host"]
            port = user_input["port"]
            password = user_input.get("password", "")

            try:
                await _test_connection(self.hass, host, port, password)
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"{host}:{port}")
                self._abort_if_unique_id_configured()
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data={"host": host, "port": port, "password": password},
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "host", default=reconfigure_entry.data.get("host", DEFAULT_HOST)
                    ): str,
                    vol.Required(
                        "port", default=reconfigure_entry.data.get("port", DEFAULT_PORT)
                    ): int,
                    vol.Optional(
                        "password", default=reconfigure_entry.data.get("password", "")
                    ): str,
                }
            ),
            errors=errors,
        )

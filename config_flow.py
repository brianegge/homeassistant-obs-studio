"""Config flow for OBS WebSocket."""

import voluptuous as vol

from homeassistant import config_entries
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

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

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

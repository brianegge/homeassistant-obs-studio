"""OBS WebSocket integration with persistent push connection."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, HEARTBEAT_INTERVAL, PLATFORMS


@dataclass
class OBSRuntimeData:
    """Runtime data for the OBS WebSocket integration."""

    connection: OBSConnection
    coordinator: OBSCoordinator


type OBSConfigEntry = ConfigEntry[OBSRuntimeData]

_LOGGER = logging.getLogger(__name__)


class OBSConnection:
    """Persistent OBS WebSocket connection with event-driven updates."""

    def __init__(
        self, hass: HomeAssistant, host: str, port: int, password: str
    ) -> None:
        self.hass = hass
        self.host = host
        self._port = port
        self._password = password
        self._req_client = None
        self._event_client = None
        self.coordinator: DataUpdateCoordinator | None = None

    @property
    def connected(self) -> bool:
        return self._req_client is not None

    def _get_kwargs(self) -> dict:
        kwargs = {"host": self.host, "port": self._port, "timeout": 10}
        if self._password:
            kwargs["password"] = self._password
        return kwargs

    async def async_connect(self) -> None:
        """Create persistent ReqClient and EventClient connections."""
        conn = self

        def _connect():
            import obsws_python as obs

            conn._req_client = obs.ReqClient(**conn._get_kwargs())

            class _Events(obs.EventClient):
                def on_stream_state_changed(self_, data):
                    conn._on_event()

            conn._event_client = _Events(**conn._get_kwargs())

        await self.hass.async_add_executor_job(_connect)

    def _on_event(self) -> None:
        """Handle OBS event from EventClient thread."""
        if self.coordinator is None:
            return
        asyncio.run_coroutine_threadsafe(
            self.coordinator.async_request_refresh(),
            self.hass.loop,
        )

    async def async_fetch_data(self) -> dict:
        """Fetch current state using the persistent ReqClient."""

        def _fetch():
            status = self._req_client.get_stream_status()
            service = self._req_client.get_stream_service_settings()
            return {"stream_status": status, "service_settings": service}

        return await self.hass.async_add_executor_job(_fetch)

    async def async_disconnect(self) -> None:
        """Disconnect both clients."""

        def _disconnect():
            for client in (self._event_client, self._req_client):
                if client:
                    try:
                        client.disconnect()
                    except Exception:
                        pass
            self._event_client = None
            self._req_client = None

        await self.hass.async_add_executor_job(_disconnect)


class OBSCoordinator(DataUpdateCoordinator):
    """Coordinator with persistent connection and event-driven refresh."""

    def __init__(
        self, hass: HomeAssistant, connection: OBSConnection
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"OBS WebSocket ({connection.host})",
            update_interval=timedelta(seconds=HEARTBEAT_INTERVAL),
        )
        self.connection = connection

    async def _async_update_data(self) -> dict:
        try:
            if not self.connection.connected:
                await self.connection.async_connect()
            return await self.connection.async_fetch_data()
        except Exception as err:
            await self.connection.async_disconnect()
            raise UpdateFailed(f"Error communicating with OBS: {err}") from err


async def async_setup_entry(hass: HomeAssistant, entry: OBSConfigEntry) -> bool:
    """Set up OBS WebSocket from a config entry."""
    connection = OBSConnection(
        hass,
        host=entry.data["host"],
        port=entry.data["port"],
        password=entry.data.get("password", ""),
    )

    await connection.async_connect()

    coordinator = OBSCoordinator(hass, connection)
    connection.coordinator = coordinator
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = OBSRuntimeData(
        connection=connection,
        coordinator=coordinator,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OBSConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.connection.async_disconnect()
    return unload_ok

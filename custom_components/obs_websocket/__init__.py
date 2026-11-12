"""OBS WebSocket integration with persistent push connection."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, TypeVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, EVENT_REFRESH_COOLDOWN, HEARTBEAT_INTERVAL, PLATFORMS


@dataclass
class OBSRuntimeData:
    """Runtime data for the OBS WebSocket integration."""

    connection: OBSConnection
    coordinator: OBSCoordinator


type OBSConfigEntry = ConfigEntry[OBSRuntimeData]

_LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")


class OBSConnection:
    """Persistent OBS WebSocket connection with event-driven updates."""

    def __init__(self, hass: HomeAssistant, host: str, port: int, password: str) -> None:
        self.hass = hass
        self.host = host
        self._port = port
        self._password = password
        self._req_client: Any | None = None
        self._event_client: Any | None = None
        self.coordinator: DataUpdateCoordinator[dict[str, Any]] | None = None

    @property
    def connected(self) -> bool:
        return self._req_client is not None

    def _get_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "host": self.host,
            "port": self._port,
            "timeout": 10,
        }
        if self._password:
            kwargs["password"] = self._password
        return kwargs

    async def async_connect(self) -> None:
        """Create persistent ReqClient and EventClient connections."""
        conn = self

        def _connect() -> None:
            import obsws_python as obs

            conn._req_client = obs.ReqClient(**conn._get_kwargs())

            class _Events(obs.EventClient):
                def on_stream_state_changed(self_: Any, data: Any) -> None:
                    conn._on_event()

                def on_record_state_changed(self_: Any, data: Any) -> None:
                    conn._on_event()

            events = _Events(**conn._get_kwargs())
            # obsws-python only dispatches events to functions registered via callback.register()
            events.callback.register(events.on_stream_state_changed)
            events.callback.register(events.on_record_state_changed)
            conn._event_client = events

        await self.hass.async_add_executor_job(_connect)

    def _on_event(self) -> None:
        """Handle OBS event from EventClient thread."""
        if self.coordinator is None:
            return
        asyncio.run_coroutine_threadsafe(
            self.coordinator.async_request_refresh(),
            self.hass.loop,
        )

    async def _async_request(self, func: Callable[[Any], _T]) -> _T:
        """Run a ReqClient call, reconnecting once if the socket is stale.

        The request socket is long-lived and can go half-open while idle:
        the client object still exists (so ``connected`` is ``True``) but the
        call hangs until its timeout or fails outright. ``connected`` cannot
        tell a live socket from a dead one, so instead of trusting it we run
        the call, and on any failure drop the client, reconnect, and retry
        once. That turns a stale socket into a completed request rather than a
        command that is silently dropped while the sensors still read fine.
        """
        last_err: Exception | None = None
        for _attempt in range(2):
            try:
                if self._req_client is None:
                    await self.async_connect()
                client = self._req_client
                if client is None:
                    raise RuntimeError("OBS WebSocket connection unavailable")
                return await self.hass.async_add_executor_job(func, client)
            except Exception as err:  # reconnect on any failure
                last_err = err
                await self.async_disconnect()
        assert last_err is not None
        raise last_err

    async def async_fetch_data(self) -> dict[str, Any]:
        """Fetch current state using the persistent ReqClient."""

        def _fetch(client: Any) -> dict[str, Any]:
            return {
                "stream_status": client.get_stream_status(),
                "record_status": client.get_record_status(),
                "service_settings": client.get_stream_service_settings(),
            }

        return await self._async_request(_fetch)

    async def async_start_stream(self) -> None:
        """Start streaming in OBS."""
        await self._async_request(lambda client: client.start_stream())

    async def async_stop_stream(self) -> None:
        """Stop streaming in OBS."""
        await self._async_request(lambda client: client.stop_stream())

    async def async_disconnect(self) -> None:
        """Disconnect both clients."""

        def _disconnect() -> None:
            for client in (self._event_client, self._req_client):
                if client:
                    with contextlib.suppress(Exception):
                        client.disconnect()
            self._event_client = None
            self._req_client = None

        await self.hass.async_add_executor_job(_disconnect)


class OBSCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator with persistent connection and event-driven refresh."""

    def __init__(self, hass: HomeAssistant, connection: OBSConnection) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"OBS WebSocket ({connection.host})",
            update_interval=timedelta(seconds=HEARTBEAT_INTERVAL),
            request_refresh_debouncer=Debouncer(
                hass,
                _LOGGER,
                cooldown=EVENT_REFRESH_COOLDOWN,
                immediate=True,
            ),
        )
        self.connection = connection
        self._was_available = True

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            # async_fetch_data connects if needed and reconnects on a stale
            # socket, so no separate connect guard is required here.
            data = await self.connection.async_fetch_data()
        except Exception as err:
            await self.connection.async_disconnect()
            if self._was_available:
                _LOGGER.warning(
                    "OBS WebSocket (%s) is unavailable: %s",
                    self.connection.host,
                    err,
                )
                self._was_available = False
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={
                    "host": self.connection.host,
                    "error": str(err),
                },
            ) from err

        if not self._was_available:
            _LOGGER.info("OBS WebSocket (%s) is available again", self.connection.host)
            self._was_available = True
        return data


async def async_setup_entry(hass: HomeAssistant, entry: OBSConfigEntry) -> bool:
    """Set up OBS WebSocket from a config entry."""
    connection = OBSConnection(
        hass,
        host=entry.data["host"],
        port=entry.data["port"],
        password=entry.data.get("password", ""),
    )

    try:
        await connection.async_connect()
    except Exception as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="connection_failed",
            translation_placeholders={"host": entry.data["host"], "error": str(err)},
        ) from err

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
        connection = entry.runtime_data.connection
        # Stop late OBS events from triggering a refresh that would reconnect.
        connection.coordinator = None
        await entry.runtime_data.coordinator.async_shutdown()
        await connection.async_disconnect()
    return unload_ok

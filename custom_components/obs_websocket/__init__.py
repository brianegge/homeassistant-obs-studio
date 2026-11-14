"""OBS WebSocket integration with persistent push connection."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, TypeVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    EVENT_REFRESH_COOLDOWN,
    HEARTBEAT_INTERVAL,
    MIN_RATE_INTERVAL,
    PLATFORMS,
    SNAPSHOT_QUALITY,
)
from .errors import OBSAuthError, is_auth_error


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
        # obsws-python's ReqClient sends a request and returns whatever reply
        # arrives next, without matching request IDs, so two requests in flight
        # on the one socket (a poll and a button press or camera snapshot) can
        # swap replies. Serialize them.
        self._request_lock = threading.Lock()
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

        try:
            await self.hass.async_add_executor_job(_connect)
        except Exception as err:
            if is_auth_error(err):
                raise OBSAuthError(str(err)) from err
            raise

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
                return await self.hass.async_add_executor_job(self._locked_call, func, client)
            except OBSAuthError:
                # A wrong password won't be fixed by retrying.
                await self.async_disconnect()
                raise
            except Exception as err:  # reconnect on any failure
                last_err = err
                await self.async_disconnect()
        assert last_err is not None
        raise last_err

    def _locked_call(self, func: Callable[[Any], _T], client: Any) -> _T:
        """Run one ReqClient call (in the executor) with the socket to itself."""
        with self._request_lock:
            return func(client)

    async def async_fetch_data(self) -> dict[str, Any]:
        """Fetch current state using the persistent ReqClient."""

        def _fetch(client: Any) -> dict[str, Any]:
            return {
                "stream_status": client.get_stream_status(),
                "record_status": client.get_record_status(),
                "service_settings": client.get_stream_service_settings(),
                "stats": client.get_stats(),
            }

        return await self._async_request(_fetch)

    async def async_start_stream(self) -> None:
        """Start streaming in OBS."""
        await self._async_request(lambda client: client.start_stream())

    async def async_stop_stream(self) -> None:
        """Stop streaming in OBS."""
        await self._async_request(lambda client: client.stop_stream())

    async def async_start_record(self) -> None:
        """Start recording in OBS."""
        await self._async_request(lambda client: client.start_record())

    async def async_stop_record(self) -> None:
        """Stop recording in OBS."""
        await self._async_request(lambda client: client.stop_record())

    async def async_get_program_screenshot(self, size: int) -> bytes:
        """Return a JPEG of the current program scene, its longer side `size` pixels."""

        def _screenshot(client: Any) -> str:
            scene = client.get_current_program_scene()
            name = getattr(scene, "scene_name", None) or scene.current_program_scene_name
            # The protocol documents width/height as a bounding box that keeps
            # the aspect ratio, but OBS stretches the image to exactly the
            # size given; derive the other side from the canvas instead.
            video = client.get_video_settings()
            width, height = screenshot_size(video.base_width, video.base_height, size)
            return client.get_source_screenshot(name, "jpg", width, height, SNAPSHOT_QUALITY).image_data

        image_data = await self._async_request(_screenshot)
        # A data URI: "data:image/jpg;base64,<payload>".
        return base64.b64decode(image_data.partition(",")[2])

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


def screenshot_size(canvas_width: int, canvas_height: int, size: int) -> tuple[int, int]:
    """Scale the canvas so its longer side is `size`, within OBS's 8-4096 limits."""
    scale = size / max(canvas_width, canvas_height)
    return (
        min(max(round(canvas_width * scale), 8), 4096),
        min(max(round(canvas_height * scale), 8), 4096),
    )


def numeric_field(obj: Any, attr: str) -> float | None:
    """Return a numeric response field, or None when it is missing."""
    value = getattr(obj, attr, None)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return value


def _skipped_pct(prev: dict[str, float | None], cur: dict[str, float | None], prefix: str) -> float | None:
    """Percent of frames skipped between two samples of a skipped/total counter pair.

    OBS's counters are cumulative (since OBS started, or since the output
    started), so a since-start ratio hides whether frames are being lost right
    now. A counter that went backwards was reset (a new stream), so measure
    from zero. No frames in the window (output not running) gives None.
    """
    skipped, total = cur[f"{prefix}_skipped"], cur[f"{prefix}_total"]
    if skipped is None or total is None:
        return None
    prev_skipped, prev_total = prev.get(f"{prefix}_skipped"), prev.get(f"{prefix}_total")
    if prev_skipped is None or prev_total is None or total < prev_total or skipped < prev_skipped:
        prev_skipped = prev_total = 0
    frames = total - prev_total
    if frames <= 0:
        return None
    return round(100 * (skipped - prev_skipped) / frames, 1)


class OBSRateTracker:
    """Turn OBS's cumulative counters into rates over the last poll window.

    Windows shorter than MIN_RATE_INTERVAL (an event refresh right after a
    poll) keep the previous rates rather than reporting a noisy ratio over a
    fraction of a second.
    """

    def __init__(self) -> None:
        self._baseline: dict[str, float | None] | None = None
        self._baseline_time = 0.0
        self.rates: dict[str, float | None] = {}

    def update(self, data: dict[str, Any], now: float) -> dict[str, float | None]:
        stream, stats = data.get("stream_status"), data.get("stats")
        streaming = bool(getattr(stream, "output_active", False))
        cur = {
            "stream_bytes": numeric_field(stream, "output_bytes"),
            "stream_skipped": numeric_field(stream, "output_skipped_frames"),
            "stream_total": numeric_field(stream, "output_total_frames"),
            "render_skipped": numeric_field(stats, "render_skipped_frames"),
            "render_total": numeric_field(stats, "render_total_frames"),
            "lag_skipped": numeric_field(stats, "output_skipped_frames"),
            "lag_total": numeric_field(stats, "output_total_frames"),
        }
        prev = self._baseline
        elapsed = now - self._baseline_time
        if prev is not None and elapsed < MIN_RATE_INTERVAL:
            return self.rates

        bitrate: float | None = None
        if not streaming:
            bitrate = 0
        elif prev is not None and cur["stream_bytes"] is not None:
            prev_bytes = prev.get("stream_bytes")
            if prev_bytes is not None and cur["stream_bytes"] >= prev_bytes:
                bitrate = round((cur["stream_bytes"] - prev_bytes) * 8 / 1000 / elapsed)

        base = prev or {}
        self.rates = {
            "stream_bitrate": bitrate,
            "stream_dropped_pct": _skipped_pct(base, cur, "stream") if streaming else None,
            "render_skipped_pct": _skipped_pct(base, cur, "render"),
            "encoding_lag_pct": _skipped_pct(base, cur, "lag"),
        }
        self._baseline, self._baseline_time = cur, now
        return self.rates


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
        self._rates = OBSRateTracker()

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            # async_fetch_data connects if needed and reconnects on a stale
            # socket, so no separate connect guard is required here.
            data = await self.connection.async_fetch_data()
        except OBSAuthError as err:
            # Marks entities unavailable and starts the reauth flow.
            self._was_available = False
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="invalid_auth",
                translation_placeholders={"host": self.connection.host},
            ) from err
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
        data["rates"] = self._rates.update(data, time.monotonic())
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
    except OBSAuthError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="invalid_auth",
            translation_placeholders={"host": entry.data["host"]},
        ) from err
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

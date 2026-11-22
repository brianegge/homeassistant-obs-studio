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
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    EVENT_PROGRAM_SCENE_CHANGED,
    EVENT_REFRESH_COOLDOWN,
    EVENT_SCENE_COLLECTION_CHANGED,
    EVENT_SCENE_COLLECTION_CHANGING,
    HEARTBEAT_INTERVAL,
    MIN_RATE_INTERVAL,
    OBS_EVENTS,
    PLATFORMS,
    SCENE_LIST_EVENTS,
    SNAPSHOT_QUALITY,
)
from .errors import (
    INVALID_RESOURCE_STATE,
    OUTPUT_NOT_RUNNING,
    OUTPUT_RUNNING,
    OBSAuthError,
    is_auth_error,
    is_request_error,
    request_error_code,
)


@dataclass
class OBSRuntimeData:
    """Runtime data for the OBS WebSocket integration."""

    connection: OBSConnection
    coordinator: OBSCoordinator


type OBSConfigEntry = ConfigEntry[OBSRuntimeData]

_LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")

# Returns a changed copy of the coordinator data.
type _Patch = Callable[[dict[str, Any]], dict[str, Any]]


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
        # A command, its follow-up and an event refresh can all find the
        # connection down at once (after an OBS restart, say). Without this
        # each would connect, and the EventClient of every pair but the last
        # would be left running with nothing to close it.
        self._connect_lock = asyncio.Lock()
        self._virtual_cam_supported = True
        self.coordinator: OBSCoordinator | None = None

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
            # A fresh connection may be to an OBS that has since gained a virtual camera.
            conn._virtual_cam_supported = True

            events = obs.EventClient(**conn._get_kwargs())
            # obsws-python only dispatches events to functions registered via
            # callback.register(), matching them by __name__ ("on_<event>").
            for event in OBS_EVENTS:
                events.callback.register(conn._make_event_handler(event))
            conn._event_client = events

        try:
            await self.hass.async_add_executor_job(_connect)
        except Exception as err:
            if is_auth_error(err):
                raise OBSAuthError(str(err)) from err
            raise

    def _make_event_handler(self, event: str) -> Callable[[Any], None]:
        """Return a callback that obsws-python dispatches for `event`."""

        def handler(data: Any) -> None:
            self._on_event(event, data)

        handler.__name__ = f"on_{event}"
        return handler

    def _on_event(self, event: str, data: Any = None) -> None:
        """Hand an OBS event from the EventClient thread to the coordinator."""
        if self.coordinator is None:
            return
        asyncio.run_coroutine_threadsafe(
            self.coordinator.async_handle_event(event, data),
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

        A request error is the exception: OBS answered, so the socket is fine
        and asking again would get the same answer. It is raised as is.
        """
        last_err: Exception | None = None
        for _attempt in range(2):
            try:
                if self._req_client is None:
                    async with self._connect_lock:
                        # Whoever held the lock may have connected already.
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
            except Exception as err:  # reconnect on any failure but a request error
                if is_request_error(err):
                    raise
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
                "scenes": parse_scene_list(client.get_scene_list()),
                "virtual_cam": self._fetch_virtual_cam(client),
            }

        return await self._async_request(_fetch)

    async def async_fetch_scenes(self) -> dict[str, Any]:
        """Fetch only the scene list and the current program scene."""
        return await self._async_request(lambda client: parse_scene_list(client.get_scene_list()))

    def _fetch_virtual_cam(self, client: Any) -> bool | None:
        """Return whether the virtual camera is on, or None if OBS has none.

        OBS answers GetVirtualCamStatus with InvalidResourceState when it has
        no virtual camera (on Linux, without the v4l2loopback module).
        obsws-python logs every failed request as an error, so stop asking
        until the next reconnect rather than logging it on every poll. Any
        other request error (NotReady while a scene collection is switching,
        say) is passing, so it fails this poll and the next one asks again.
        """
        if not self._virtual_cam_supported:
            return None
        try:
            return bool_field(client.get_virtual_cam_status(), "output_active")
        except Exception as err:
            if request_error_code(err) != INVALID_RESOURCE_STATE:
                raise
            _LOGGER.info("OBS at %s has no virtual camera: %s", self.host, err)
            self._virtual_cam_supported = False
            return None

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

    async def async_start_virtual_cam(self) -> None:
        """Start the OBS virtual camera."""
        await self._async_request_unless(OUTPUT_RUNNING, lambda client: client.start_virtual_cam())

    async def async_stop_virtual_cam(self) -> None:
        """Stop the OBS virtual camera."""
        await self._async_request_unless(OUTPUT_NOT_RUNNING, lambda client: client.stop_virtual_cam())

    async def _async_request_unless(self, done_code: int, func: Callable[[Any], Any]) -> None:
        """Run a command, counting OBS's `done_code` answer as success.

        `done_code` is the request error OBS gives when it is already in the
        state the command asks for, such as OutputRunning for a start.
        """
        try:
            await self._async_request(func)
        except Exception as err:
            if request_error_code(err) != done_code:
                raise

    async def async_set_program_scene(self, scene: str) -> None:
        """Switch the OBS program output to `scene`."""
        await self._async_request(lambda client: client.set_current_program_scene(scene))

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


def bool_field(obj: Any, attr: str) -> bool | None:
    """Return a boolean response field, or None when it is missing."""
    value = getattr(obj, attr, None)
    return value if isinstance(value, bool) else None


def _int_or_zero(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def parse_scene_list(response: Any) -> dict[str, Any]:
    """Reduce a GetSceneList response to the program scene and the scene names.

    OBS lists scenes bottom first (sceneIndex 0 is the last scene in the
    Scenes dock), so sort by sceneIndex descending to match the dock.
    """
    scenes = getattr(response, "scenes", None)
    entries = [
        scene
        for scene in (scenes if isinstance(scenes, list) else [])
        if isinstance(scene, dict) and isinstance(scene.get("sceneName"), str)
    ]
    entries.sort(key=lambda scene: _int_or_zero(scene.get("sceneIndex")), reverse=True)
    current = getattr(response, "current_program_scene_name", None)
    return {
        "current": current if isinstance(current, str) else None,
        "names": [scene["sceneName"] for scene in entries],
    }


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
        self._polling = False
        self._deferred: list[_Patch] = []
        self._collection_switching = False
        self._scene_refresh = Debouncer(
            hass,
            _LOGGER,
            cooldown=EVENT_REFRESH_COOLDOWN,
            immediate=True,
            function=self._async_refresh_scenes,
        )

    async def async_shutdown(self) -> None:
        """Cancel the poll and any pending scene list refresh."""
        await super().async_shutdown()
        self._scene_refresh.async_shutdown()

    async def async_handle_event(self, event: str, data: Any = None) -> None:
        """Act on an OBS event with the least work that keeps the data right."""
        if event == EVENT_SCENE_COLLECTION_CHANGING:
            self._collection_switching = True
        elif event == EVENT_PROGRAM_SCENE_CHANGED and isinstance(name := getattr(data, "scene_name", None), str):
            await self.async_program_scene_changed(name)
        elif event in SCENE_LIST_EVENTS:
            if event == EVENT_SCENE_COLLECTION_CHANGED:
                self._collection_switching = False
            await self._scene_refresh.async_call()
        else:
            await self.async_request_refresh()

    async def async_program_scene_changed(self, name: str) -> None:
        """Record the program scene OBS reported, or a command just set."""
        await self._async_patch_or_refresh(lambda data: {**data, "scenes": {**data.get("scenes", {}), "current": name}})

    async def async_virtual_cam_changed(self, active: bool) -> None:
        """Record the virtual camera state a command just set.

        OBS answers start and stop before it has acted on them, so a poll
        right after the command could read the old state.
        """
        await self._async_patch_or_refresh(lambda data: {**data, "virtual_cam": active})

    async def _async_refresh_scenes(self) -> None:
        """Fetch the scene list on its own, leaving the rest of the data as it is."""
        if self._collection_switching:
            # OBS would only answer NotReady; current_scene_collection_changed follows.
            return
        if self.data is None or not self.last_update_success:
            await self.async_request_refresh()
            return
        try:
            scenes = await self.connection.async_fetch_scenes()
        except Exception as err:
            if is_request_error(err):
                # OBS answered but had no list to give. Entities stay as they
                # are; the next scene event or poll fetches it.
                _LOGGER.debug("OBS at %s could not list its scenes: %s", self.connection.host, err)
                return
            # The connection is gone: let the poll report it and reconnect.
            await self.async_request_refresh()
            return
        await self._async_patch_or_refresh(lambda data: {**data, "scenes": scenes})

    async def _async_patch_or_refresh(self, patch: _Patch) -> None:
        """Change part of the data without a poll, or poll if that is not possible."""
        if not self._async_patch(patch):
            await self.async_request_refresh()

    @callback
    def _async_patch(self, patch: _Patch) -> bool:
        """Apply `patch` to the data and tell the entities. False if only a poll will do.

        This is not async_set_updated_data(): that restarts the heartbeat
        timer, so scene cuts closer together than the heartbeat would keep
        the poll from ever running.
        """
        if self._polling:
            # The poll may already have read what this replaces; apply it on top.
            self._deferred.append(patch)
            return True
        if self.data is None or not self.last_update_success:
            return False
        self.data = patch(self.data)
        self.async_update_listeners()
        return True

    async def _async_update_data(self) -> dict[str, Any]:
        self._polling = True
        try:
            data = await self._async_poll()
            for patch in self._deferred:
                data = patch(data)
            return data
        finally:
            self._polling = False
            self._deferred.clear()

    async def _async_poll(self) -> dict[str, Any]:
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
            # A request error means OBS answered: the connection is still good.
            if not is_request_error(err):
                await self.connection.async_disconnect()
                self._collection_switching = False
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
        # OBS answered everything, so it is not mid scene collection switch.
        self._collection_switching = False
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

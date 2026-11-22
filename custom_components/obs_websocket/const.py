"""Constants for the OBS WebSocket integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "obs_websocket"

DEFAULT_HOST: Final = "localhost"
DEFAULT_PORT: Final = 4455

HEARTBEAT_INTERVAL: Final = 60

# OBS emits STARTING then STARTED (or STOPPING then STOPPED) in quick succession.
# The first event refreshes immediately; later ones within this window are coalesced
# into a single trailing refresh.
EVENT_REFRESH_COOLDOWN: Final = 0.5

# Rates (bitrate, skipped-frame percentages) are measured over at least this
# many seconds; a refresh sooner than that keeps the previous values.
MIN_RATE_INTERVAL: Final = 10

# Program snapshot camera: default bounding box when the frontend gives no
# size, and JPEG quality (0-100).
DEFAULT_SNAPSHOT_SIZE: Final = 1280
SNAPSHOT_QUALITY: Final = 80

PLATFORMS: Final[list[str]] = ["button", "camera", "select", "sensor", "switch"]

# OBS events the integration listens for (snake_case, as obsws-python names
# them), grouped by what each costs. A scene cut can happen every few seconds,
# so it must not run the full poll.

# Output state changes: a full poll, debounced.
REFRESH_EVENTS: Final[tuple[str, ...]] = (
    "stream_state_changed",
    "record_state_changed",
    "virtualcam_state_changed",
)

# Carries the new scene name, so no request is needed.
EVENT_PROGRAM_SCENE_CHANGED: Final = "current_program_scene_changed"

# OBS answers every request with NotReady from this event until
# current_scene_collection_changed.
EVENT_SCENE_COLLECTION_CHANGING: Final = "current_scene_collection_changing"
EVENT_SCENE_COLLECTION_CHANGED: Final = "current_scene_collection_changed"

# The scene list changed: fetch only GetSceneList, debounced. A scene
# collection change fires a burst of scene created/removed events.
SCENE_LIST_EVENTS: Final[tuple[str, ...]] = (
    "scene_list_changed",
    "scene_created",
    "scene_removed",
    "scene_name_changed",
    EVENT_SCENE_COLLECTION_CHANGED,
)

OBS_EVENTS: Final[tuple[str, ...]] = (
    *REFRESH_EVENTS,
    EVENT_PROGRAM_SCENE_CHANGED,
    EVENT_SCENE_COLLECTION_CHANGING,
    *SCENE_LIST_EVENTS,
)

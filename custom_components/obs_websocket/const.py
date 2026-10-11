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

PLATFORMS: Final[list[str]] = ["button", "sensor"]

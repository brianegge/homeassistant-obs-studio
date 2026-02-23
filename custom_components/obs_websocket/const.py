"""Constants for the OBS WebSocket integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "obs_websocket"

DEFAULT_HOST: Final = "localhost"
DEFAULT_PORT: Final = 4455

HEARTBEAT_INTERVAL: Final = 60

PLATFORMS: Final[list[str]] = ["sensor"]

"""Errors for the OBS WebSocket integration."""

from __future__ import annotations

# obsws-python reports auth failures as a generic OBSSDKError, so they can only be told
# apart by message. A wrong password makes OBS close the socket (code 4009) during the
# identify handshake, which the library surfaces as an unparseable identify response.
_AUTH_ERROR_MESSAGES = (
    "authentication enabled but no password provided",
    "failed to identify client with the server, please check connection settings",
)


class OBSAuthError(Exception):
    """OBS rejected the WebSocket password."""


def is_auth_error(err: BaseException) -> bool:
    """Return True if an obsws-python error means the password was rejected."""
    return type(err).__name__ == "OBSSDKError" and any(msg in str(err) for msg in _AUTH_ERROR_MESSAGES)


# obs-websocket RequestStatus codes the integration acts on.
OUTPUT_RUNNING = 500  # a start request for an output that is already running
OUTPUT_NOT_RUNNING = 501  # a stop request for an output that is not running
INVALID_RESOURCE_STATE = 604  # among others: OBS has no virtual camera


def is_request_error(err: BaseException) -> bool:
    """Return True if OBS answered a request with an error status (e.g. a resource it lacks)."""
    return type(err).__name__ == "OBSSDKRequestError"


def request_error_code(err: BaseException) -> int | None:
    """Return the RequestStatus code OBS answered with, or None if `err` is not a request error."""
    return getattr(err, "code", None) if is_request_error(err) else None

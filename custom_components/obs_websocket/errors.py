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

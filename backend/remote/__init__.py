"""Opt-in, LAN-only phone companion for Murmur AI."""

from .companion_server import (
    app,
    companion_status,
    is_lan_address,
    start_companion,
    stop_companion,
)

__all__ = ["app", "companion_status", "is_lan_address", "start_companion", "stop_companion"]

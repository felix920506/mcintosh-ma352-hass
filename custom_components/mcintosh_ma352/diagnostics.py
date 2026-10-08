"""Diagnostics for the McIntosh MA352 integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from . import MA352ConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MA352ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    hub = entry.runtime_data
    return {
        "entry": {"data": dict(entry.data), "options": dict(entry.options)},
        "connected": hub.client.connected,
        "available": hub.available,
        "info": asdict(hub.client.info),
        "state": dict(hub.client.state.values),
    }

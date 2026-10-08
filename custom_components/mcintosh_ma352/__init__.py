"""The McIntosh MA352 integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_BAUDRATE, CONF_SERIAL_PORT
from .hub import MA352Hub
from .ma352 import DEFAULT_BAUDRATE, MA352Error

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
]

type MA352ConfigEntry = ConfigEntry[MA352Hub]


async def async_setup_entry(hass: HomeAssistant, entry: MA352ConfigEntry) -> bool:
    """Set up McIntosh MA352 from a config entry."""
    hub = MA352Hub(
        hass,
        entry.data[CONF_SERIAL_PORT],
        entry.data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE),
    )
    try:
        await hub.async_start()
    except MA352Error as err:
        await hub.async_stop()
        raise ConfigEntryNotReady(
            f"Unable to connect to MA352 at {entry.data[CONF_SERIAL_PORT]}: {err}"
        ) from err

    entry.runtime_data = hub
    hub.start_background(
        lambda coro, name: entry.async_create_background_task(hass, coro, name)
    )
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MA352ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_stop()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: MA352ConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)

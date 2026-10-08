"""Connection manager for a McIntosh MA352."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN, INPUT_REFRESH_DELAY, POLL_INTERVAL, RECONNECT_INTERVAL
from .ma352 import (
    BOOT_TIMEOUT,
    CMD_INPUT,
    CMD_POWER,
    CMD_STATUS_ENABLE,
    MA352,
    MA352CommandError,
    MA352Error,
)

_LOGGER = logging.getLogger(__name__)


class MA352Hub:
    """Owns the client, keeps it connected and fans out state updates."""

    def __init__(self, hass: HomeAssistant, url: str, baudrate: int) -> None:
        """Initialize."""
        self.hass = hass
        self.client = MA352(url, baudrate)
        self.available = False
        self._listeners: list[CALLBACK_TYPE] = []
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._refresh_unsub: CALLBACK_TYPE | None = None
        self._boot_task: asyncio.Task | None = None
        self._last_power: int | None = None
        self._last_input: int | None = None
        self._unsub_client = [
            self.client.add_listener(self._on_state),
            self.client.add_connection_listener(self._on_connection),
        ]

    @property
    def unique_id(self) -> str | None:
        """Return the serial number."""
        return self.client.info.serial_number

    # ------------------------------------------------------------ lifecycle
    async def async_start(self) -> None:
        """Connect and read initial state; raises MA352Error on failure."""
        try:
            await self.client.connect()
            await self.async_refresh()
        except MA352Error:
            await self.client.disconnect()
            raise

    def start_background(self, create_task: Callable[..., asyncio.Task]) -> None:
        """Start the poll/reconnect loop using the config entry task factory."""
        self._task = create_task(self._run(), f"{DOMAIN} {self.client.url}")

    async def async_stop(self) -> None:
        """Stop everything and disconnect."""
        if self._refresh_unsub:
            self._refresh_unsub()
            self._refresh_unsub = None
        for task in (self._task, self._boot_task):
            if task:
                task.cancel()
        self._task = self._boot_task = None
        for unsub in self._unsub_client:
            unsub()
        await self.client.disconnect()

    async def _run(self) -> None:
        while True:
            if self.client.connected:
                try:
                    await asyncio.wait_for(self._wake.wait(), POLL_INTERVAL)
                except TimeoutError:
                    pass
                self._wake.clear()
                if not self.client.connected or self._boot_task:
                    continue
                try:
                    await self.async_refresh()
                except MA352Error as err:
                    _LOGGER.warning("Lost contact with MA352 at %s: %s", self.client.url, err)
                    await self.client.disconnect()
                    self._set_available(False)
            else:
                try:
                    await self.client.connect()
                    await self.async_refresh()
                    _LOGGER.info("Reconnected to MA352 at %s", self.client.url)
                except MA352Error as err:
                    _LOGGER.debug("Reconnect to %s failed: %s", self.client.url, err)
                    await self.client.disconnect()
                    await asyncio.sleep(RECONNECT_INTERVAL)

    async def async_refresh(self) -> None:
        """Query the full state and make sure status push is enabled."""
        state = await self.client.query()
        if state.power and state.get(CMD_STATUS_ENABLE) != 1:
            await self.client.command(CMD_STATUS_ENABLE, 1)
        self._set_available(True)

    # ------------------------------------------------------------ commands
    async def async_command(self, name: str, param: str | int | None = None) -> None:
        """Send a command, translating errors for Home Assistant."""
        if self._boot_task:
            # Don't feed the amplifier's boot-time queue (see below).
            await asyncio.shield(self._boot_task)
        try:
            await self.client.command(name, param)
        except MA352CommandError as err:
            raise HomeAssistantError(f"MA352 rejected ({name} {param}): {err}") from err
        except MA352Error as err:
            raise HomeAssistantError(f"Error communicating with MA352: {err}") from err

    # ------------------------------------------------------------ listeners
    @callback
    def add_listener(self, listener: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Register an entity update callback."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _fire(self) -> None:
        for listener in list(self._listeners):
            listener()

    def _set_available(self, available: bool) -> None:
        if self.available != available:
            self.available = available
            self._fire()

    def _on_connection(self, connected: bool) -> None:
        if not connected:
            self._set_available(False)
            self._wake.set()

    def _on_state(self) -> None:
        values = self.client.state.values
        power, inp = values.get(CMD_POWER), values.get(CMD_INPUT)
        if self._last_power == 0 and power == 1:
            # Powered on (from HA, front panel or remote).
            self._start_boot_wait()
        elif self._last_input is not None and inp != self._last_input:
            # Trim/EQ settings are per input; read them back.
            self._schedule_refresh()
        self._last_power, self._last_input = power, inp
        self._fire()

    def _start_boot_wait(self) -> None:
        if self._boot_task is None:
            self._boot_task = self.hass.async_create_background_task(
                self._async_wait_for_boot(), f"{DOMAIN} boot wait"
            )

    async def _async_wait_for_boot(self) -> None:
        """Hold the command queue until the amplifier has finished booting.

        The amplifier queues commands received while booting and runs them
        all afterwards. A single read-only probe answered after boot avoids
        stacking up (timed out, then retried) commands such as volume steps.
        Other commands wait on the client lock meanwhile.
        """
        try:
            await self.client.command(CMD_POWER, timeout=BOOT_TIMEOUT)
            _LOGGER.debug("MA352 finished booting")
            await self.async_refresh()
        except MA352Error as err:
            _LOGGER.warning("MA352 did not come back after power-on: %s", err)
            await self.client.disconnect()
        finally:
            self._boot_task = None

    def _schedule_refresh(self) -> None:
        if self._refresh_unsub:
            self._refresh_unsub()

        @callback
        def _refresh(_now) -> None:
            self._refresh_unsub = None
            self._wake.set()

        self._refresh_unsub = async_call_later(self.hass, INPUT_REFRESH_DELAY, _refresh)

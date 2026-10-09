"""Asyncio client for the McIntosh MA352 RS232 control protocol.

This module has no Home Assistant dependencies so it can be tested and used
standalone. Commands are ASCII frames of the form ``(XXX par)``; the amplifier
echoes the command (with absolute values) as acknowledgement and, when status
reporting is enabled (``STA 1``), pushes the same frames whenever its state
changes (e.g. front panel knob).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import logging
import re

import serial
import serial_asyncio_fast

_LOGGER = logging.getLogger(__name__)

DEFAULT_BAUDRATE = 115200
BAUDRATES = [9600, 19200, 38400, 57600, 115200]

COMMAND_TIMEOUT = 2.0
# After power-on the unit is unresponsive for ~16 s. It does not drop
# commands sent meanwhile; it queues and executes them once booted.
BOOT_TIMEOUT = 45.0
QUERY_TIMEOUT = 4.0
# Quiet period that marks the end of a multi-frame (QRY) response.
QUERY_SETTLE = 0.4
# Max duration of a status dump (QRY reply or power-on), starting at (MA352).
DUMP_WINDOW = 1.5
# Unsolicited volume changes of at least this many steps are passthrough
# transitions; the knob and remote report every single step.
PASSTHROUGH_JUMP = 2
# Volume reported in passthrough on the unit tested (FW 1.07); not settable
# in the setup menu.
PASSTHROUGH_LEVEL = 69

INPUTS: dict[int, str] = {
    1: "BAL 1",
    2: "BAL 2",
    3: "UNBAL 1",
    4: "UNBAL 2",
    5: "UNBAL 3",
    6: "MM PHONO",
}
PHONO_INPUT = 6

# Phono capacitance index 1..16 -> 50..800 pF
PHONO_CAPACITANCE = {i: i * 50 for i in range(1, 17)}

# Display brightness index 1..4 -> percent
DISPLAY_BRIGHTNESS = {1: 25, 2: 50, 3: 75, 4: 100}

# Command names
CMD_POWER = "PWR"
CMD_VOLUME = "VOL"
CMD_MUTE = "MUT"
CMD_OUTPUT_1 = "OP1"
CMD_OUTPUT_2 = "OP2"
CMD_HEADPHONES = "HPS"
CMD_INPUT = "INP"
CMD_BALANCE = "TBA"
CMD_INPUT_TRIM = "TIN"
CMD_EQUALIZER = "TEQ"
CMD_PHONO_CAPACITANCE = "TPC"
CMD_MONO = "TMO"
# The PDF lists meter lights as "TTM" but firmware 1.07 answers to "TML".
CMD_METER_LIGHTS = "TML"
CMD_TUBE_LIGHTS = "TTL"
CMD_DISPLAY_BRIGHTNESS = "TDB"
# Undocumented: display auto-off (seen in QRY output, confirmed on the unit).
CMD_DISPLAY_AUTO_OFF = "TDS"
CMD_HEADPHONE_HXD = "THH"
CMD_QUERY = "QRY"
CMD_STATUS_ENABLE = "STA"

_FRAME_RE = re.compile(r"\(([^()]*)\)")
_STATE_RE = re.compile(r"^([A-Z0-9]{3})(?: (-?\+?\d+))?$")


class MA352Error(Exception):
    """Base error."""


class MA352ConnectionError(MA352Error):
    """Connection to the amplifier failed or was lost."""


class MA352CommandError(MA352Error):
    """The amplifier rejected a command (ERROR frame)."""


class MA352TimeoutError(MA352Error):
    """No response to a command."""


@dataclass
class MA352Info:
    """Product information."""

    model: str | None = None
    serial_number: str | None = None
    firmware: str | None = None


@dataclass
class MA352State:
    """Last known state; values are the raw integers reported by the unit."""

    values: dict[str, int] = field(default_factory=dict)
    # Inferred, None if undeterminable (see MA352._track_passthrough).
    passthrough: bool | None = False

    def get(self, name: str) -> int | None:
        """Return a raw value."""
        return self.values.get(name)

    @property
    def power(self) -> bool:
        """Return True when the amplifier is on."""
        return self.values.get(CMD_POWER) == 1


def parse_frames(buffer: str) -> tuple[list[str], str]:
    """Split a receive buffer into frame payloads and the unparsed remainder."""
    frames: list[str] = []
    end = 0
    for match in _FRAME_RE.finditer(buffer):
        frames.append(match.group(1).strip())
        end = match.end()
    rest = buffer[end:]
    # Drop anything before an opening parenthesis; keep a partial frame.
    start = rest.find("(")
    rest = rest[start:] if start >= 0 else ""
    if len(rest) > 256:  # garbage protection
        rest = ""
    return frames, rest


class MA352:
    """Connection to a McIntosh MA352 over a local or network serial port."""

    def __init__(self, url: str, baudrate: int = DEFAULT_BAUDRATE) -> None:
        """Initialize. ``url`` is a device path or a pyserial URL (socket://...)."""
        self.url = url
        self.baudrate = baudrate
        self.info = MA352Info()
        self.state = MA352State()
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._read_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[], None]] = []
        self._connection_listeners: list[Callable[[bool], None]] = []
        # Pending command: (name, future) - only one command in flight.
        self._pending: tuple[str, asyncio.Future[str]] | None = None
        # Value that completes the pending command (absolute volume sets ramp
        # in 1 % steps, each pushed as a frame).
        self._pending_value: int | None = None
        self._query_state_seen = False
        self._rx_event = asyncio.Event()
        self._dump_until = 0.0
        # Volume the unit reports while in passthrough.
        self.passthrough_level = PASSTHROUGH_LEVEL
        self._passthrough_known = False

    # ------------------------------------------------------------------ io
    @property
    def connected(self) -> bool:
        """Return True if the transport is open."""
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        """Open the serial connection."""
        if self.connected:
            return
        try:
            self._reader, self._writer = await asyncio.wait_for(
                serial_asyncio_fast.open_serial_connection(
                    url=self.url,
                    baudrate=self.baudrate,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    xonxoff=False,
                    rtscts=False,
                ),
                timeout=10,
            )
        except (OSError, serial.SerialException, TimeoutError) as err:
            self._reader = self._writer = None
            raise MA352ConnectionError(f"Unable to open {self.url}: {err}") from err
        self._read_task = asyncio.get_running_loop().create_task(self._read_loop())
        _LOGGER.debug("Connected to %s", self.url)
        self._notify_connection(True)

    async def disconnect(self) -> None:
        """Close the connection."""
        task, self._read_task = self._read_task, None
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._close_transport()

    def _close_transport(self) -> None:
        was_connected = self._writer is not None
        if self._writer is not None:
            try:
                self._writer.close()
            except Exception:  # noqa: BLE001
                pass
        self._reader = self._writer = None
        self._passthrough_known = False
        if self._pending and not self._pending[1].done():
            self._pending[1].set_exception(MA352ConnectionError("Connection lost"))
        if was_connected:
            self._notify_connection(False)

    async def _read_loop(self) -> None:
        assert self._reader is not None
        buffer = ""
        try:
            while True:
                data = await self._reader.read(1024)
                if not data:
                    raise MA352ConnectionError("Connection closed by peer")
                self._rx_event.set()
                text = data.decode("ascii", errors="ignore")
                buffer += text.replace("\x00", "")
                frames, buffer = parse_frames(buffer)
                for frame in frames:
                    self._handle_frame(frame)
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Read loop for %s ended: %s", self.url, err)
            self._read_task = None
            self._close_transport()

    def _handle_frame(self, frame: str) -> None:
        _LOGGER.debug("RX (%s)", frame)
        if frame.startswith("ERROR"):
            if self._pending and not self._pending[1].done():
                self._pending[1].set_exception(MA352CommandError(frame))
            else:
                _LOGGER.debug("Unsolicited error: %s", frame)
            return
        if frame.startswith("Serial Number:"):
            self.info.serial_number = frame.split(":", 1)[1].strip()
            return
        if frame.startswith("FW Version:"):
            self.info.firmware = frame.split(":", 1)[1].strip()
            return
        if frame.startswith("MA"):
            self.info.model = frame
            self._dump_until = asyncio.get_running_loop().time() + DUMP_WINDOW
            return

        match = _STATE_RE.match(frame)
        if not match:
            _LOGGER.debug("Ignoring unknown frame: %s", frame)
            return
        name, value = match.group(1), match.group(2)
        changed = False
        if value is not None:
            self._query_state_seen = True
            old = self.state.values.get(name)
            changed = old != int(value)
            self.state.values[name] = int(value)
            changed |= self._track_passthrough(name, old, int(value))
            if name == CMD_HEADPHONES or (name == CMD_POWER and value == "0"):
                self._dump_until = 0.0  # last frame of a dump
        # Resolve the pending command before notifying: a listener may send a
        # new command (eager tasks) that must not be answered by this frame.
        if (
            self._pending
            and self._pending[0] == name
            and not self._pending[1].done()
            and (self._pending_value is None or value == str(self._pending_value))
        ):
            self._pending[1].set_result(frame)
        if changed:
            self._notify()

    def _track_passthrough(self, name: str, old: int | None, new: int) -> bool:
        """Infer passthrough mode; return True if it changed.

        In passthrough (enabled e.g. by a 12 V trigger) the unit reports a
        fixed volume (69 % on the unit tested) and ignores the knob and
        remote; RS232 volume commands are accepted but discarded on exit. There is no explicit status, but entering and leaving always
        push one unsolicited volume frame: a jump to the level and back (or
        a repeat of the same value if the volume already was at the level).
        The knob and remote push exactly one frame per 1 % step.

        ``passthrough`` is None when undeterminable: a status snapshot taken
        at exactly the level (after connect or power-on) looks the same in
        both modes until the next knob step or transition.
        """
        before = self.state.passthrough
        level = self.passthrough_level
        if name == CMD_POWER:
            if new == 0:
                self.state.passthrough = False
            elif new != old:
                self._passthrough_known = False
        elif name == CMD_VOLUME:
            in_dump = asyncio.get_running_loop().time() < self._dump_until
            solicited = self._pending is not None and self._pending[0] == CMD_VOLUME
            if in_dump:
                # Full status: decide after connect/power-on; afterwards it
                # only corrects a passthrough state whose exit was missed
                # (volume control is locked then, so it must still read the
                # level; while undetermined, HA may have changed it).
                if not self._passthrough_known:
                    self.state.passthrough = None if new == level else False
                    self._passthrough_known = True
                elif self.state.passthrough and new != level:
                    self.state.passthrough = False
            elif not solicited and old is not None:
                if abs(new - old) == 1:
                    # Knob/remote step: these are ignored in passthrough.
                    self.state.passthrough = False
                elif new == level and old != level:
                    self.state.passthrough = True
                elif new == level:
                    # Repeated level: a transition in either direction.
                    if self.state.passthrough is not None:
                        self.state.passthrough = not self.state.passthrough
                else:
                    self.state.passthrough = False
                _LOGGER.debug(
                    "Volume %s -> %s, passthrough %s", old, new, self.state.passthrough
                )
        return before != self.state.passthrough

    async def _write(self, payload: str) -> None:
        if not self.connected:
            raise MA352ConnectionError("Not connected")
        assert self._writer is not None
        _LOGGER.debug("TX %s", payload)
        try:
            self._writer.write(f"{payload}\r".encode("ascii"))
            await self._writer.drain()
        except (OSError, serial.SerialException) as err:
            self._close_transport()
            raise MA352ConnectionError(str(err)) from err

    # ------------------------------------------------------------ commands
    async def command(
        self,
        name: str,
        param: str | int | None = None,
        timeout: float | None = None,
    ) -> int | None:
        """Send a command and return the value from the acknowledgement.

        Firmware 1.07 does not acknowledge most set commands that leave the
        value unchanged (e.g. ``VOL 22`` at 22, or ``VOL U`` at the limit).
        Such commands are skipped when the known value already matches, and a
        missing acknowledgement is resolved by querying the current value.
        """
        if isinstance(param, int) and self.state.values.get(name) == param:
            return param
        payload = f"({name})" if param is None else f"({name} {param})"
        async with self._lock:
            try:
                frame = await self._transact(
                    name,
                    payload,
                    timeout,
                    param if name == CMD_VOLUME and isinstance(param, int) else None,
                )
            except MA352TimeoutError:
                if param is None:
                    raise
                _LOGGER.debug("No acknowledgement for %s, querying %s", payload, name)
                frame = await self._transact(name, f"({name})", timeout)
        match = _STATE_RE.match(frame)
        return int(match.group(2)) if match and match.group(2) is not None else None

    async def _transact(
        self,
        name: str,
        payload: str,
        timeout: float | None,
        value: int | None = None,
    ) -> str:
        """Send a frame and wait for the reply named ``name`` (lock held).

        With ``value``, wait for the frame reporting that value; frames
        before it (a volume ramp) count as part of the reply.
        """
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._pending = (name, future)
        self._pending_value = value
        try:
            await self._write(payload)
            return await asyncio.wait_for(future, timeout or COMMAND_TIMEOUT)
        except TimeoutError as err:
            raise MA352TimeoutError(f"No response to {payload}") from err
        finally:
            self._pending = None
            self._pending_value = None

    async def query(self) -> MA352State:
        """Request the full status (QRY) and wait for the response to settle."""
        async with self._lock:
            loop = asyncio.get_running_loop()
            start = loop.time()
            self.info.model = None
            self._query_state_seen = False
            self._rx_event.clear()
            await self._write(f"({CMD_QUERY})")
            while True:
                remaining = QUERY_TIMEOUT - (loop.time() - start)
                if remaining <= 0:
                    break
                try:
                    await asyncio.wait_for(
                        self._rx_event.wait(), min(QUERY_SETTLE, remaining)
                    )
                except TimeoutError:
                    if self.info.model is not None:
                        break  # quiet period after the response
                    continue
                self._rx_event.clear()
            if self.info.model is None:
                raise MA352TimeoutError("No response to (QRY)")
            if not self.connected:
                raise MA352ConnectionError("Connection lost")
            # In standby the unit only reports product information.
            if not self._query_state_seen:
                if self.state.values.get(CMD_POWER) != 0:
                    self.state.values[CMD_POWER] = 0
                    self._notify()
        return self.state

    def _notify(self) -> None:
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Error in MA352 listener")

    def _notify_connection(self, connected: bool) -> None:
        for listener in list(self._connection_listeners):
            try:
                listener(connected)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Error in MA352 connection listener")

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a state-change callback; returns an unsubscribe function."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def add_connection_listener(
        self, listener: Callable[[bool], None]
    ) -> Callable[[], None]:
        """Register a connection-change callback."""
        self._connection_listeners.append(listener)
        return lambda: self._connection_listeners.remove(listener)

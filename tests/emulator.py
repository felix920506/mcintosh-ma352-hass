"""A TCP emulator of the MA352 RS232 port, modelled on a real unit (FW 1.07).

Run standalone with ``python -m tests.emulator [port]`` and point the
integration at ``socket://127.0.0.1:<port>``.
"""

from __future__ import annotations

import asyncio
import re
import sys

INFO = ["MA352", "Serial Number: AHW0001", "FW Version: 1.07"]

DEFAULT_STATE = {
    "PWR": 1,
    "VOL": 22,
    "MUT": 0,
    "OP1": 1,
    "OP2": 1,
    "INP": 1,
    "STA": 1,
    "TBA": 0,
    "TIN": 0,
    "TEQ": 1,
    "TPC": 1,
    "TMO": 0,
    "TML": 1,
    "TTL": 1,
    "TDB": 2,
    "TDS": 1,
    "THH": 1,
    "HPS": 0,
}

RANGES = {
    "PWR": (0, 1),
    "VOL": (0, 100),
    "MUT": (0, 1),
    "OP1": (0, 1),
    "OP2": (0, 1),
    "INP": (1, 6),
    "STA": (0, 1),
    "TBA": (-50, 50),
    "TIN": (-12, 12),
    "TEQ": (0, 1),
    "TPC": (1, 16),
    "TMO": (0, 1),
    "TML": (0, 1),
    "TTL": (0, 1),
    "TDB": (1, 4),
    "TDS": (0, 1),
    "THH": (0, 1),
}
READ_ONLY = {"HPS"}
# Set commands that are not acknowledged when the value does not change
# (observed on FW 1.07; MUT, INP, OP1, OP2 and TDB always echo).
SILENT_WHEN_UNCHANGED = {"VOL", "TBA", "TIN", "TEQ", "TMO", "TTL", "TML", "TDS", "STA"}
STEP = {
    "VOL": {"U": 1, "D": -1},
    "INP": {"U": 1, "D": -1},
    "TBA": {"R": 1, "L": -1},
    "TIN": {"U": 1, "D": -1},
    "TPC": {"U": 1, "D": -1},
}
ERR_CMD = "ERROR - Invalid Command"
ERR_PAR = "ERROR - Invalid Parameter"
ERR_INP = "ERROR - Invalid Input"

_FRAME = re.compile(r"\(([^()]*)\)")


class MA352Emulator:
    """Emulated amplifier serving one or more TCP clients."""

    def __init__(self) -> None:
        self.state = dict(DEFAULT_STATE)
        self.disabled_inputs: set[int] = set()
        self.received: list[str] = []
        self.mute_responses = False
        # Seconds the unit is unresponsive after power-on (real unit: ~16).
        self.boot_time = 0.0
        self._boot_queue: list[str] | None = None
        self._writers: list[asyncio.StreamWriter] = []
        self._server: asyncio.Server | None = None
        self.port = 0

    async def start(self, port: int = 0) -> int:
        self._server = await asyncio.start_server(self._client, "127.0.0.1", port)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        for writer in self._writers:
            writer.close()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    def drop_clients(self) -> None:
        """Simulate a network failure."""
        for writer in list(self._writers):
            writer.close()

    @property
    def url(self) -> str:
        return f"socket://127.0.0.1:{self.port}"

    def send(self, *frames: str) -> None:
        """Send frames to all clients (as the unit does with NUL padding)."""
        data = b"\x00\x00" + "".join(f"({f})" for f in frames).encode() + b"\x00\x00"
        for writer in self._writers:
            writer.write(data)

    def front_panel(self, name: str, value: int) -> None:
        """Simulate a local state change, pushed when STA is enabled."""
        if name == "PWR" and value == 1 and self.state["PWR"] == 0:
            # Real unit: power button pushes a full dump, then boots.
            self.send(*self.handle("PWR 1"))
            return
        self.state[name] = value
        if self.state["STA"] == 1:
            self.send(f"{name} {value}")

    async def _client(self, reader, writer) -> None:
        self._writers.append(writer)
        buf = ""
        try:
            while data := await reader.read(256):
                buf += data.decode(errors="ignore")
                for match in _FRAME.finditer(buf):
                    self.received.append(match.group(1))
                    if self._boot_queue is not None:
                        self._boot_queue.append(match.group(1))
                    elif not self.mute_responses and (reply := self.handle(match.group(1))):
                        self.send(*reply)
                buf = buf[buf.rfind(")") + 1 :] if ")" in buf else buf
        finally:
            self._writers.remove(writer)

    def handle(self, payload: str) -> list[str]:
        parts = payload.split()
        if not parts:
            return [ERR_CMD]
        name, args = parts[0], parts[1:]
        if name == "QRY":
            if self.state["PWR"] != 1:
                return list(INFO)
            return INFO + [f"{k} {v}" for k, v in self.state.items()]
        if name not in self.state:
            return [ERR_CMD]
        if self.state["PWR"] != 1 and name != "PWR":
            return [ERR_CMD]
        if name == "THH" and self.state["HPS"] != 1:
            return [ERR_CMD]
        if name == "TPC" and self.state["INP"] != 6:
            return [ERR_INP]
        if not args:
            return [f"{name} {self.state[name]}"]
        if name in READ_ONLY:
            return [ERR_PAR]
        arg = args[0]
        low, high = RANGES[name]
        if arg in STEP.get(name, {}):
            value = self.state[name] + STEP[name][arg]
            if name == "INP":
                value = (value - 1) % 6 + 1
            value = max(low, min(high, value))
        else:
            try:
                value = int(arg)
            except ValueError:
                return [ERR_PAR]
            if not low <= value <= high:
                return [ERR_PAR]
        if name == "INP" and value in self.disabled_inputs:
            return [ERR_PAR]
        if name in SILENT_WHEN_UNCHANGED and value == self.state[name]:
            return []
        if name == "PWR" and value == 1 and self.state["PWR"] == 0:
            # Real unit: answers with a full dump, then boots while queueing
            # (not dropping) commands.
            self.state["PWR"] = 1
            if self.boot_time:
                self._boot_queue = []
                asyncio.get_running_loop().call_later(self.boot_time, self._booted)
            return self.handle("QRY")
        if name == "VOL" and arg not in STEP["VOL"]:
            # Absolute volume ramps in 1 % steps, each pushed.
            step = 1 if value > self.state[name] else -1
            start = self.state[name]
            self.state[name] = value
            return [f"VOL {v}" for v in range(start + step, value + step, step)]
        self.state[name] = value
        return [f"{name} {value}"]

    def _booted(self) -> None:
        queue, self._boot_queue = self._boot_queue or [], None
        for payload in queue:
            self.send(*self.handle(payload))


async def _main(port: int) -> None:
    emulator = MA352Emulator()
    await emulator.start(port)
    print(f"MA352 emulator listening on {emulator.url}")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(_main(int(sys.argv[1]) if len(sys.argv) > 1 else 4001))

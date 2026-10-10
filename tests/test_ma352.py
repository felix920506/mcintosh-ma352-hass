"""Tests for the protocol client."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.mcintosh_ma352.ma352 import (
    MA352,
    MA352CommandError,
    MA352ConnectionError,
    MA352TimeoutError,
    parse_frames,
)

from .emulator import MA352Emulator


def test_parse_frames() -> None:
    """Frames are split, NUL/CRLF tolerated and partial frames kept."""
    frames, rest = parse_frames("(MA352)(VOL 22)junk(MUT")
    assert frames == ["MA352", "VOL 22"]
    assert rest == "(MUT"
    frames, rest = parse_frames(rest + " 1)\r\n")
    assert frames == ["MUT 1"]
    assert rest == ""


async def test_query_and_commands(emulator: MA352Emulator) -> None:
    """Query fills info/state; commands return the acknowledged value."""
    client = MA352(emulator.url)
    await client.connect()
    try:
        state = await client.query()
        assert client.info.model == "MA352"
        assert client.info.serial_number == "AHW0001"
        assert client.info.firmware == "1.07"
        assert state.power
        assert state.get("VOL") == 22

        assert await client.command("VOL", "D") == 21
        assert state.get("VOL") == 21
        # Absolute sets ramp; the command completes at the target.
        assert await client.command("VOL", 30) == 30
        assert await client.command("VOL", 25) == 25
        await client.command("VOL", 21)
        assert await client.command("TBA", -5) == -5

        with pytest.raises(MA352CommandError, match="Invalid Input"):
            await client.command("TPC")
        with pytest.raises(MA352CommandError, match="Invalid Parameter"):
            await client.command("VOL", 101)
    finally:
        await client.disconnect()


async def test_standby_query(emulator: MA352Emulator) -> None:
    """In standby QRY only returns product info -> power off."""
    emulator.state["PWR"] = 0
    client = MA352(emulator.url)
    await client.connect()
    try:
        state = await client.query()
        assert not state.power
        assert client.info.serial_number == "AHW0001"
        with pytest.raises(MA352CommandError, match="Invalid Command"):
            await client.command("VOL", 10)
    finally:
        await client.disconnect()


async def test_push_updates(emulator: MA352Emulator) -> None:
    """Unsolicited status frames update state and notify listeners."""
    client = MA352(emulator.url)
    await client.connect()
    calls = []
    client.add_listener(lambda: calls.append(client.state.get("VOL")))
    try:
        emulator.front_panel("VOL", 30)
        for _ in range(50):
            if calls:
                break
            await asyncio.sleep(0.01)
        assert calls == [30]
    finally:
        await client.disconnect()


async def test_timeout_and_disconnect(emulator: MA352Emulator) -> None:
    """No answer raises a timeout; a dropped link is detected."""
    client = MA352(emulator.url)
    events = []
    client.add_connection_listener(events.append)
    await client.connect()
    emulator.mute_responses = True
    with pytest.raises(MA352TimeoutError):
        await client.command("VOL")
    emulator.drop_clients()
    for _ in range(50):
        if not client.connected:
            break
        await asyncio.sleep(0.01)
    assert not client.connected
    assert events == [True, False]
    with pytest.raises(MA352ConnectionError):
        await client.command("VOL")


async def test_connect_failure() -> None:
    """Refused connections raise MA352ConnectionError."""
    client = MA352("socket://127.0.0.1:1")
    with pytest.raises(MA352ConnectionError):
        await client.connect()


async def test_unchanged_value_not_acknowledged(emulator: MA352Emulator) -> None:
    """Set commands that change nothing get no echo from the unit."""
    client = MA352(emulator.url)
    await client.connect()
    try:
        await client.query()
        emulator.received.clear()
        # Known to match: not sent at all.
        assert await client.command("VOL", 22) == 22
        assert emulator.received == []
        # Stale cache: sent, unacknowledged, then confirmed with a query.
        client.state.values["TTL"] = 0
        assert await client.command("TTL", 1) == 1
        assert emulator.received == ["TTL 1", "TTL"]
        # Relative step at the limit.
        emulator.state["VOL"] = 0
        client.state.values["VOL"] = 0
        emulator.received.clear()
        assert await client.command("VOL", "D") == 0
        assert emulator.received == ["VOL D", "VOL"]
    finally:
        await client.disconnect()


async def test_slider_burst(emulator: MA352Emulator) -> None:
    """Rapid volume sets: queued ones are superseded, the last one wins."""
    client = MA352(emulator.url)
    await client.connect()
    try:
        await client.query()
        updates: list[int | None] = []
        client.add_listener(lambda: updates.append(client.state.get("VOL")))
        emulator.received.clear()
        # 15 is in flight while 20, 18 and 22 queue up behind it; 22 matched
        # the (stale) value when requested but must still be applied.
        await asyncio.gather(*(client.command("VOL", v) for v in (15, 20, 18, 22)))
        assert emulator.received == ["VOL 15", "VOL 22"]
        assert client.state.get("VOL") == emulator.state["VOL"] == 22
        # One state update per command, not one per ramp step.
        assert updates == [15, 22]

        # A relative step after an absolute set is applied after it.
        emulator.received.clear()
        await asyncio.gather(client.command("VOL", 10), client.command("VOL", "U"))
        assert emulator.received == ["VOL 10", "VOL U"]
        assert client.state.get("VOL") == 11
    finally:
        await client.disconnect()


async def test_telnet_connection() -> None:
    """A serial server in telnet mode works like a raw TCP one."""
    emu = MA352Emulator(telnet=True)
    await emu.start()
    client = MA352(emu.url)
    try:
        await client.connect()
        state = await client.query()
        assert client.info.serial_number == "AHW0001"
        assert state.get("VOL") == 22
        assert await client.command("VOL", 30) == 30
        emu.front_panel("MUT", 1)
        for _ in range(50):
            if state.get("MUT") == 1:
                break
            await asyncio.sleep(0.01)
        assert state.get("MUT") == 1
        assert emu.received == ["QRY", "VOL 30"]
        emu.drop_clients()
        for _ in range(50):
            if not client.connected:
                break
            await asyncio.sleep(0.01)
        assert not client.connected
    finally:
        await client.disconnect()
        await emu.stop()


async def test_telnet_bad_url() -> None:
    """A telnet URL without a host raises MA352ConnectionError."""
    client = MA352("telnet://")
    with pytest.raises(MA352ConnectionError):
        await client.connect()

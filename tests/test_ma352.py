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

"""Fixtures for McIntosh MA352 tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest
import pytest_socket

from .emulator import MA352Emulator


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations."""
    return


@pytest.fixture(autouse=True)
def allow_localhost_sockets(socket_enabled):
    """The emulator is a real TCP server on 127.0.0.1."""
    pytest_socket.socket_allow_hosts(["127.0.0.1"], allow_unix_socket=True)


@pytest.fixture(autouse=True)
def fast_timers():
    """Shorten reconnect/poll timers."""
    with (
        patch("custom_components.mcintosh_ma352.hub.RECONNECT_INTERVAL", 0.05),
        patch("custom_components.mcintosh_ma352.hub.INPUT_REFRESH_DELAY", 0),
        patch("custom_components.mcintosh_ma352.ma352.QUERY_SETTLE", 0.1),
        patch("custom_components.mcintosh_ma352.ma352.COMMAND_TIMEOUT", 0.5),
        patch("custom_components.mcintosh_ma352.ma352.QUERY_TIMEOUT", 1),
    ):
        yield


@pytest.fixture
async def emulator() -> AsyncGenerator[MA352Emulator]:
    """Start an emulated amplifier."""
    emu = MA352Emulator()
    await emu.start()
    yield emu
    await emu.stop()

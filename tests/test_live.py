"""Live tests against a real MA352. Skipped unless MA352_LIVE_URL is set.

    MA352_LIVE_URL=socket://host:port pytest tests/test_live.py -s

Only low-risk changes are made and restored: tube lights, mute, a 1% volume
step down then up, display brightness. Volume is never raised above its
starting level. MA352_LIVE_POWER=1 additionally power-cycles the unit.
MA352_LIVE_WATCH=<seconds> logs state changes while you operate the amp.
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest
import pytest_socket
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.media_player import ATTR_MEDIA_VOLUME_LEVEL, DOMAIN as MP_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, STATE_ON
from homeassistant.core import HomeAssistant

from custom_components.mcintosh_ma352.const import CONF_BAUDRATE, CONF_SERIAL_PORT, DOMAIN

URL = os.environ.get("MA352_LIVE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="MA352_LIVE_URL not set")

MP = "media_player.mcintosh_ma352"


@pytest.fixture(autouse=True)
def fast_timers():
    """Use real timings against real hardware."""
    yield


@pytest.fixture(autouse=True)
def allow_localhost_sockets(socket_enabled):
    """Allow the network serial server."""
    pytest_socket.socket_allow_hosts(
        ["127.0.0.1", URL.split("//")[1].split(":")[0]] if URL and "//" in URL else ["127.0.0.1"]
    )


@pytest.fixture
def expected_lingering_tasks() -> bool:
    return True


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_SERIAL_PORT: URL, CONF_BAUDRATE: 115200},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _call(hass, domain, service, entity_id, **data):
    await hass.services.async_call(domain, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True)


def _dump(hass: HomeAssistant, label: str) -> None:
    print(f"--- {label}")
    for state in sorted(hass.states.async_all(), key=lambda s: s.entity_id):
        if "mcintosh" in state.entity_id:
            extra = ""
            if state.entity_id == MP:
                extra = {k: v for k, v in state.attributes.items() if k in ("volume_level", "is_volume_muted", "source")}
            print(f"{state.entity_id:50} {state.state} {extra}")


async def test_live_basic(hass: HomeAssistant) -> None:
    """Read state and make reversible low-risk changes."""
    entry = await _setup(hass)
    _dump(hass, "initial")
    hub = entry.runtime_data
    if not hub.client.state.power:
        pytest.skip("amplifier is in standby")
    vol = hub.client.state.get("VOL")
    tube = "switch.mcintosh_ma352_tube_lights"
    initial_tube = hass.states.get(tube).state

    await _call(hass, "switch", "toggle", tube)
    assert hass.states.get(tube).state != initial_tube
    await _call(hass, "switch", "toggle", tube)
    assert hass.states.get(tube).state == initial_tube

    await _call(hass, MP_DOMAIN, "volume_mute", MP, is_volume_muted=True)
    assert hass.states.get(MP).attributes["is_volume_muted"] is True
    await _call(hass, MP_DOMAIN, "volume_mute", MP, is_volume_muted=False)

    if vol > 0:
        await _call(hass, MP_DOMAIN, "volume_down", MP)
        assert hub.client.state.get("VOL") == vol - 1
        await _call(hass, MP_DOMAIN, "volume_set", MP, volume_level=vol / 100)
        assert hub.client.state.get("VOL") == vol

    bright = "select.mcintosh_ma352_display_brightness"
    initial_bright = hass.states.get(bright).state
    await _call(hass, "select", "select_option", bright, option="100%")
    await _call(hass, "select", "select_option", bright, option=initial_bright)
    assert hass.states.get(bright).state == initial_bright
    _dump(hass, "final")
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.skipif(not os.environ.get("MA352_LIVE_POWER"), reason="MA352_LIVE_POWER not set")
async def test_live_power_cycle(hass: HomeAssistant) -> None:
    """Power off/on via HA; a volume step during boot is held until ready."""
    entry = await _setup(hass)
    hub = entry.runtime_data
    assert hub.client.state.power
    vol = hub.client.state.get("VOL")
    await _call(hass, MP_DOMAIN, "turn_off", MP)
    _dump(hass, "off")
    await asyncio.sleep(5)
    await _call(hass, MP_DOMAIN, "turn_on", MP)
    start = time.monotonic()
    # Issued during boot: must wait, and execute exactly once.
    await _call(hass, MP_DOMAIN, "volume_down", MP)
    print(f"volume_down completed after {time.monotonic() - start:.1f}s")
    assert hub.client.state.get("VOL") == vol - 1
    await asyncio.sleep(3)
    assert hub.client.state.get("VOL") == vol - 1  # no late duplicates
    await _call(hass, MP_DOMAIN, "volume_set", MP, volume_level=vol / 100)
    assert hub.client.state.get("VOL") == vol
    assert hass.states.get(MP).state == STATE_ON
    _dump(hass, "on")
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.skipif(not os.environ.get("MA352_LIVE_WATCH"), reason="MA352_LIVE_WATCH not set")
async def test_live_watch(hass: HomeAssistant) -> None:
    """Log every state change while someone operates the amplifier."""
    entry = await _setup(hass)
    _dump(hass, "initial")
    start = time.monotonic()

    def _log(event) -> None:
        new = event.data["new_state"]
        if new and "mcintosh" in new.entity_id:
            attrs = {k: v for k, v in new.attributes.items() if k in ("volume_level", "is_volume_muted", "source")}
            print(f"{time.monotonic() - start:6.1f}s {new.entity_id} -> {new.state} {attrs}", flush=True)

    hass.bus.async_listen("state_changed", _log)
    await asyncio.sleep(float(os.environ["MA352_LIVE_WATCH"]))
    _dump(hass, "final")
    await hass.config_entries.async_unload(entry.entry_id)

"""Tests for setup and entities."""

from __future__ import annotations

import asyncio

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.media_player import (
    ATTR_INPUT_SOURCE,
    ATTR_MEDIA_VOLUME_LEVEL,
    ATTR_MEDIA_VOLUME_MUTED,
    DOMAIN as MP_DOMAIN,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.mcintosh_ma352.const import (
    CONF_BAUDRATE,
    CONF_MAX_VOLUME,
    CONF_SERIAL_PORT,
    DOMAIN,
)

from .emulator import MA352Emulator

MP = "media_player.mcintosh_ma352"


async def _setup(hass: HomeAssistant, emulator: MA352Emulator, **options) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="AHW0001",
        data={CONF_SERIAL_PORT: emulator.url, CONF_BAUDRATE: 115200},
        options=options,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _wait_for(hass: HomeAssistant, predicate, timeout: float = 2) -> None:
    for _ in range(int(timeout / 0.02)):
        await hass.async_block_till_done()
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met")


async def test_setup_and_entities(hass: HomeAssistant, emulator: MA352Emulator) -> None:
    """All entities are created with state from the unit."""
    entry = await _setup(hass, emulator)
    state = hass.states.get(MP)
    assert state.state == STATE_ON
    assert state.attributes[ATTR_MEDIA_VOLUME_LEVEL] == 0.22
    assert state.attributes[ATTR_INPUT_SOURCE] == "BAL 1"
    assert state.attributes[ATTR_MEDIA_VOLUME_MUTED] is False
    assert hass.states.get("switch.mcintosh_ma352_output_1").state == STATE_ON
    assert hass.states.get("switch.mcintosh_ma352_tube_lights").state == STATE_ON
    assert hass.states.get("switch.mcintosh_ma352_mono").state == STATE_OFF
    assert hass.states.get("number.mcintosh_ma352_balance").state == "0"
    assert hass.states.get("number.mcintosh_ma352_input_trim").state == "0.0"
    assert hass.states.get("select.mcintosh_ma352_display_brightness").state == "50%"
    assert hass.states.get("binary_sensor.mcintosh_ma352_headphones").state == STATE_OFF
    # Need phono input / headphones respectively.
    assert hass.states.get("select.mcintosh_ma352_phono_capacitance").state == STATE_UNAVAILABLE
    assert hass.states.get("switch.mcintosh_ma352_headphone_hxd").state == STATE_UNAVAILABLE
    # STA was enabled; nothing else sent beyond QRY.
    assert emulator.received == ["QRY"]

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_not_ready(hass: HomeAssistant) -> None:
    """An unreachable port retries setup later."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="AHW0001",
        data={CONF_SERIAL_PORT: "socket://127.0.0.1:1", CONF_BAUDRATE: 115200},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_enables_status_push(hass: HomeAssistant, emulator: MA352Emulator) -> None:
    """If status push is off it gets enabled."""
    emulator.state["STA"] = 0
    entry = await _setup(hass, emulator)
    assert emulator.state["STA"] == 1
    await hass.config_entries.async_unload(entry.entry_id)


async def test_media_player_services(hass: HomeAssistant, emulator: MA352Emulator) -> None:
    """Volume, mute and source commands reach the unit."""
    entry = await _setup(hass, emulator, **{CONF_MAX_VOLUME: 30})

    await hass.services.async_call(
        MP_DOMAIN, "volume_set", {ATTR_ENTITY_ID: MP, ATTR_MEDIA_VOLUME_LEVEL: 0.25}, blocking=True
    )
    assert emulator.state["VOL"] == 25
    assert hass.states.get(MP).attributes[ATTR_MEDIA_VOLUME_LEVEL] == 0.25

    # Clamped to max volume
    await hass.services.async_call(
        MP_DOMAIN, "volume_set", {ATTR_ENTITY_ID: MP, ATTR_MEDIA_VOLUME_LEVEL: 0.9}, blocking=True
    )
    assert emulator.state["VOL"] == 30
    await hass.services.async_call(MP_DOMAIN, "volume_up", {ATTR_ENTITY_ID: MP}, blocking=True)
    assert emulator.state["VOL"] == 30
    await hass.services.async_call(MP_DOMAIN, "volume_down", {ATTR_ENTITY_ID: MP}, blocking=True)
    assert emulator.state["VOL"] == 29
    await hass.services.async_call(MP_DOMAIN, "volume_up", {ATTR_ENTITY_ID: MP}, blocking=True)
    assert emulator.state["VOL"] == 30

    await hass.services.async_call(
        MP_DOMAIN, "volume_mute", {ATTR_ENTITY_ID: MP, ATTR_MEDIA_VOLUME_MUTED: True}, blocking=True
    )
    assert emulator.state["MUT"] == 1
    assert hass.states.get(MP).attributes[ATTR_MEDIA_VOLUME_MUTED] is True

    await hass.services.async_call(
        MP_DOMAIN, "select_source", {ATTR_ENTITY_ID: MP, ATTR_INPUT_SOURCE: "MM PHONO"}, blocking=True
    )
    assert emulator.state["INP"] == 6
    assert hass.states.get(MP).attributes[ATTR_INPUT_SOURCE] == "MM PHONO"
    # Phono capacitance becomes available on the phono input.
    cap = "select.mcintosh_ma352_phono_capacitance"
    assert hass.states.get(cap).state == "50 pF"
    await hass.services.async_call(
        "select", "select_option", {ATTR_ENTITY_ID: cap, "option": "200 pF"}, blocking=True
    )
    assert emulator.state["TPC"] == 4

    emulator.disabled_inputs.add(2)
    with pytest.raises(HomeAssistantError, match="Invalid Parameter"):
        await hass.services.async_call(
            MP_DOMAIN, "select_source", {ATTR_ENTITY_ID: MP, ATTR_INPUT_SOURCE: "BAL 2"}, blocking=True
        )
    await hass.config_entries.async_unload(entry.entry_id)


async def test_power(hass: HomeAssistant, emulator: MA352Emulator) -> None:
    """Power off makes dependent entities unavailable; power on restores them."""
    entry = await _setup(hass, emulator)
    tube = "switch.mcintosh_ma352_tube_lights"

    await hass.services.async_call(MP_DOMAIN, "turn_off", {ATTR_ENTITY_ID: MP}, blocking=True)
    assert emulator.state["PWR"] == 0
    assert hass.states.get(MP).state == STATE_OFF
    assert ATTR_MEDIA_VOLUME_LEVEL not in hass.states.get(MP).attributes
    assert hass.states.get(tube).state == STATE_UNAVAILABLE

    emulator.received.clear()
    await hass.services.async_call(MP_DOMAIN, "turn_on", {ATTR_ENTITY_ID: MP}, blocking=True)
    assert hass.states.get(MP).state == STATE_ON
    # A full refresh is scheduled after power-on.
    await _wait_for(hass, lambda: "QRY" in emulator.received)
    assert hass.states.get(tube).state == STATE_ON
    await hass.config_entries.async_unload(entry.entry_id)


async def test_switch_number_select(hass: HomeAssistant, emulator: MA352Emulator) -> None:
    """Switch, number and select entities send the right commands."""
    entry = await _setup(hass, emulator)
    await hass.services.async_call(
        "switch", "turn_off", {ATTR_ENTITY_ID: "switch.mcintosh_ma352_tube_lights"}, blocking=True
    )
    assert emulator.state["TTL"] == 0
    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: "switch.mcintosh_ma352_mono"}, blocking=True
    )
    assert emulator.state["TMO"] == 1
    await hass.services.async_call(
        "number", "set_value",
        {ATTR_ENTITY_ID: "number.mcintosh_ma352_input_trim", "value": -2.5},
        blocking=True,
    )
    assert emulator.state["TIN"] == -5
    assert hass.states.get("number.mcintosh_ma352_input_trim").state == "-2.5"
    await hass.services.async_call(
        "number", "set_value",
        {ATTR_ENTITY_ID: "number.mcintosh_ma352_balance", "value": 7},
        blocking=True,
    )
    assert emulator.state["TBA"] == 7
    await hass.services.async_call(
        "select", "select_option",
        {ATTR_ENTITY_ID: "select.mcintosh_ma352_display_brightness", "option": "100%"},
        blocking=True,
    )
    assert emulator.state["TDB"] == 4
    await hass.config_entries.async_unload(entry.entry_id)


async def test_push_and_headphones(hass: HomeAssistant, emulator: MA352Emulator) -> None:
    """Front panel changes are pushed into Home Assistant."""
    entry = await _setup(hass, emulator)
    emulator.front_panel("VOL", 40)
    await _wait_for(hass, lambda: hass.states.get(MP).attributes.get(ATTR_MEDIA_VOLUME_LEVEL) == 0.4)
    emulator.front_panel("HPS", 1)
    await _wait_for(
        hass, lambda: hass.states.get("binary_sensor.mcintosh_ma352_headphones").state == STATE_ON
    )
    assert hass.states.get("switch.mcintosh_ma352_headphone_hxd").state == STATE_ON
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reconnect(hass: HomeAssistant, emulator: MA352Emulator) -> None:
    """A dropped connection goes unavailable then recovers."""
    entry = await _setup(hass, emulator)
    emulator.drop_clients()
    await _wait_for(hass, lambda: hass.states.get(MP).state == STATE_UNAVAILABLE)
    await _wait_for(hass, lambda: hass.states.get(MP).state == STATE_ON)
    await hass.config_entries.async_unload(entry.entry_id)


async def test_commands_wait_for_boot(hass: HomeAssistant, emulator: MA352Emulator) -> None:
    """Commands issued while the amp boots are held back, not queued on the amp."""
    emulator.state["PWR"] = 0
    emulator.boot_time = 0.5
    entry = await _setup(hass, emulator)
    assert hass.states.get(MP).state == STATE_OFF

    await hass.services.async_call(MP_DOMAIN, "turn_on", {ATTR_ENTITY_ID: MP}, blocking=True)
    assert hass.states.get(MP).state == STATE_ON
    emulator.received.clear()
    # Would time out (0.5 s in tests) if sent straight into the boot window.
    await hass.services.async_call(MP_DOMAIN, "volume_up", {ATTR_ENTITY_ID: MP}, blocking=True)
    await hass.services.async_call(MP_DOMAIN, "volume_up", {ATTR_ENTITY_ID: MP}, blocking=True)
    assert emulator.state["VOL"] == 24
    # Only the single boot probe was sent before the volume commands.
    assert emulator.received[:2] == ["PWR", "QRY"]
    assert emulator.received.count("VOL U") == 2
    assert hass.states.get(MP).attributes[ATTR_MEDIA_VOLUME_LEVEL] == 0.24
    await hass.config_entries.async_unload(entry.entry_id)


async def test_front_panel_power_on(hass: HomeAssistant, emulator: MA352Emulator) -> None:
    """Power-on from the remote is picked up and state re-read after boot."""
    emulator.state["PWR"] = 0
    emulator.boot_time = 1.5  # longer than the (patched) 1 s query timeout
    entry = await _setup(hass, emulator)
    tube = "switch.mcintosh_ma352_tube_lights"
    assert hass.states.get(tube).state == STATE_UNAVAILABLE
    emulator.received.clear()
    states: list[str] = []
    hass.bus.async_listen(
        "state_changed",
        lambda ev: ev.data["entity_id"] == MP and states.append(ev.data["new_state"].state),
    )
    emulator.front_panel("PWR", 1)  # dump, then 1.5 s boot
    hub = entry.runtime_data
    await _wait_for(hass, lambda: hub._boot_task is not None)
    await _wait_for(hass, lambda: hub._boot_task is None, timeout=5)
    await hass.async_block_till_done()
    # The probe was answered after boot, then state was re-read; never unavailable.
    assert emulator.received[:2] == ["PWR", "QRY"]
    assert STATE_UNAVAILABLE not in states
    assert hass.states.get(MP).state == STATE_ON
    await hass.config_entries.async_unload(entry.entry_id)


async def test_set_current_value(hass: HomeAssistant, emulator: MA352Emulator) -> None:
    """Setting the current value succeeds without error."""
    entry = await _setup(hass, emulator)
    await hass.services.async_call(
        MP_DOMAIN, "volume_set", {ATTR_ENTITY_ID: MP, ATTR_MEDIA_VOLUME_LEVEL: 0.22}, blocking=True
    )
    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: "switch.mcintosh_ma352_tube_lights"}, blocking=True
    )
    await hass.services.async_call(
        "number", "set_value",
        {ATTR_ENTITY_ID: "number.mcintosh_ma352_balance", "value": 0},
        blocking=True,
    )
    emulator.state["VOL"] = 0
    emulator.front_panel("VOL", 0)
    await _wait_for(hass, lambda: hass.states.get(MP).attributes[ATTR_MEDIA_VOLUME_LEVEL] == 0)
    await hass.services.async_call(MP_DOMAIN, "volume_down", {ATTR_ENTITY_ID: MP}, blocking=True)
    assert hass.states.get(MP).attributes[ATTR_MEDIA_VOLUME_LEVEL] == 0
    await hass.config_entries.async_unload(entry.entry_id)


PASSTHROUGH = "binary_sensor.mcintosh_ma352_passthrough"


async def test_passthrough(hass: HomeAssistant, emulator: MA352Emulator) -> None:
    """Passthrough is inferred from the volume jump and blocks volume control."""
    entry = await _setup(hass, emulator)
    assert hass.states.get(PASSTHROUGH).state == STATE_OFF
    features = hass.states.get(MP).attributes["supported_features"]

    emulator.set_passthrough(True)
    await _wait_for(hass, lambda: hass.states.get(PASSTHROUGH).state == STATE_ON)
    state = hass.states.get(MP)
    assert ATTR_MEDIA_VOLUME_LEVEL not in state.attributes
    assert state.attributes["passthrough"] is True
    assert state.attributes["supported_features"] != features
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(MP_DOMAIN, "volume_down", {ATTR_ENTITY_ID: MP}, blocking=True)
    assert emulator.state["VOL"] == 69
    # Mute still works.
    await hass.services.async_call(
        MP_DOMAIN, "volume_mute", {ATTR_ENTITY_ID: MP, ATTR_MEDIA_VOLUME_MUTED: True}, blocking=True
    )
    assert emulator.state["MUT"] == 1

    emulator.set_passthrough(False)
    await _wait_for(hass, lambda: hass.states.get(PASSTHROUGH).state == STATE_OFF)
    assert hass.states.get(MP).attributes[ATTR_MEDIA_VOLUME_LEVEL] == 0.22
    assert hass.states.get(MP).attributes["supported_features"] == features
    await hass.config_entries.async_unload(entry.entry_id)


async def test_passthrough_at_startup(hass: HomeAssistant, emulator: MA352Emulator) -> None:
    """Starting at 69 is ambiguous; the exit jump away from 69 resolves it."""
    emulator.state["VOL"] = 30
    emulator.set_passthrough(True)
    entry = await _setup(hass, emulator)
    assert hass.states.get(PASSTHROUGH).state == STATE_UNKNOWN
    emulator.set_passthrough(False)
    await _wait_for(hass, lambda: hass.states.get(PASSTHROUGH).state == STATE_OFF)
    assert hass.states.get(MP).attributes[ATTR_MEDIA_VOLUME_LEVEL] == 0.3
    await hass.config_entries.async_unload(entry.entry_id)


async def test_knob_to_69_is_not_passthrough(hass: HomeAssistant, emulator: MA352Emulator) -> None:
    """Single steps never count as passthrough, even onto 69 or via HA."""
    emulator.state["VOL"] = 67
    entry = await _setup(hass, emulator)
    emulator.front_panel("VOL", 68)
    emulator.front_panel("VOL", 69)
    emulator.front_panel("VOL", 70)
    await _wait_for(hass, lambda: hass.states.get(MP).attributes[ATTR_MEDIA_VOLUME_LEVEL] == 0.7)
    assert hass.states.get(PASSTHROUGH).state == STATE_OFF
    await hass.services.async_call(
        MP_DOMAIN, "volume_set", {ATTR_ENTITY_ID: MP, ATTR_MEDIA_VOLUME_LEVEL: 0.69}, blocking=True
    )
    await hass.services.async_call(
        MP_DOMAIN, "volume_set", {ATTR_ENTITY_ID: MP, ATTR_MEDIA_VOLUME_LEVEL: 0.2}, blocking=True
    )
    assert hass.states.get(PASSTHROUGH).state == STATE_OFF
    await hass.config_entries.async_unload(entry.entry_id)


async def test_passthrough_exit_missed(hass: HomeAssistant, emulator: MA352Emulator) -> None:
    """An exit missed while disconnected is corrected on reconnect."""
    entry = await _setup(hass, emulator)
    emulator.set_passthrough(True)
    await _wait_for(hass, lambda: hass.states.get(PASSTHROUGH).state == STATE_ON)
    emulator.mute_responses = True
    emulator.drop_clients()
    await _wait_for(hass, lambda: hass.states.get(MP).state == STATE_UNAVAILABLE)
    emulator.state["VOL"] = 22  # left passthrough while we were away
    emulator.mute_responses = False
    await _wait_for(hass, lambda: hass.states.get(PASSTHROUGH).state == STATE_OFF, timeout=5)
    assert hass.states.get(MP).attributes[ATTR_MEDIA_VOLUME_LEVEL] == 0.22
    await hass.config_entries.async_unload(entry.entry_id)


async def test_passthrough_volume_already_69(
    hass: HomeAssistant, emulator: MA352Emulator
) -> None:
    """With the volume already at 69 transitions repeat (VOL 69)."""
    emulator.state["VOL"] = 69
    entry = await _setup(hass, emulator)
    assert hass.states.get(PASSTHROUGH).state == STATE_UNKNOWN
    # Still unknown after a transition from an unknown state.
    emulator.set_passthrough(True)
    emulator.set_passthrough(False)
    await asyncio.sleep(0.1)
    assert hass.states.get(PASSTHROUGH).state == STATE_UNKNOWN
    # A knob step proves normal mode.
    emulator.front_panel("VOL", 68)
    await _wait_for(hass, lambda: hass.states.get(PASSTHROUGH).state == STATE_OFF)
    emulator.front_panel("VOL", 69)
    await asyncio.sleep(0.1)
    assert hass.states.get(PASSTHROUGH).state == STATE_OFF
    # Now known: repeated 69 frames toggle.
    emulator.set_passthrough(True)
    await _wait_for(hass, lambda: hass.states.get(PASSTHROUGH).state == STATE_ON)
    emulator.set_passthrough(False)
    await _wait_for(hass, lambda: hass.states.get(PASSTHROUGH).state == STATE_OFF)
    await hass.config_entries.async_unload(entry.entry_id)

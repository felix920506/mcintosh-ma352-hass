"""Tests for the config flow."""

from __future__ import annotations

from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.mcintosh_ma352.const import (
    CONF_BAUDRATE,
    CONF_MAX_VOLUME,
    CONF_SERIAL_PORT,
    DOMAIN,
)

from .emulator import MA352Emulator


def _no_ports():
    return patch("custom_components.mcintosh_ma352.config_flow.list_ports.comports", return_value=[])


async def test_user_flow(hass: HomeAssistant, emulator: MA352Emulator) -> None:
    """A responding MA352 creates an entry keyed on its serial number."""
    with _no_ports():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_SERIAL_PORT: f" {emulator.url} ", CONF_BAUDRATE: "115200"},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "McIntosh MA352 (AHW0001)"
    assert result["data"] == {CONF_SERIAL_PORT: emulator.url, CONF_BAUDRATE: 115200}
    assert result["result"].unique_id == "AHW0001"
    await hass.config_entries.async_unload(result["result"].entry_id)


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    """Connection failures show an error and keep the form."""
    with _no_ports():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_SERIAL_PORT: "socket://127.0.0.1:1", CONF_BAUDRATE: "115200"},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_no_answer(hass: HomeAssistant, emulator: MA352Emulator) -> None:
    """A port that never answers is reported as cannot_connect."""
    emulator.mute_responses = True
    with _no_ports():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SERIAL_PORT: emulator.url, CONF_BAUDRATE: "115200"}
        )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_already_configured(
    hass: HomeAssistant, emulator: MA352Emulator
) -> None:
    """The same amplifier can't be added twice."""
    MockConfigEntry(
        domain=DOMAIN,
        unique_id="AHW0001",
        data={CONF_SERIAL_PORT: "/dev/ttyUSB0", CONF_BAUDRATE: 115200},
    ).add_to_hass(hass)
    with _no_ports():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SERIAL_PORT: emulator.url, CONF_BAUDRATE: "115200"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure(hass: HomeAssistant, emulator: MA352Emulator) -> None:
    """Reconfigure releases the port, validates and updates the entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="AHW0001",
        data={CONF_SERIAL_PORT: emulator.url, CONF_BAUDRATE: 115200},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    with _no_ports():
        result = await entry.start_reconfigure_flow(hass)
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SERIAL_PORT: emulator.url, CONF_BAUDRATE: "57600"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_BAUDRATE] == 57600
    assert entry.state is config_entries.ConfigEntryState.LOADED
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reconfigure_wrong_amp(hass: HomeAssistant, emulator: MA352Emulator) -> None:
    """Pointing an entry at a different amplifier is rejected."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="OTHER",
        data={CONF_SERIAL_PORT: "socket://127.0.0.1:1", CONF_BAUDRATE: 115200},
    )
    entry.add_to_hass(hass)
    with _no_ports():
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SERIAL_PORT: emulator.url, CONF_BAUDRATE: "115200"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "wrong_amplifier"}


async def test_options(hass: HomeAssistant, emulator: MA352Emulator) -> None:
    """The volume limit option is stored."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="AHW0001",
        data={CONF_SERIAL_PORT: emulator.url, CONF_BAUDRATE: 115200},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MAX_VOLUME: 40}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_MAX_VOLUME: 40}
    await hass.config_entries.async_unload(entry.entry_id)

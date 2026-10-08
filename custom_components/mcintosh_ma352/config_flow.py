"""Config flow for the McIntosh MA352 integration."""

from __future__ import annotations

import logging
from typing import Any

from serial.tools import list_ports
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_BAUDRATE,
    CONF_MAX_VOLUME,
    CONF_SERIAL_PORT,
    DEFAULT_MAX_VOLUME,
    DOMAIN,
    MODEL,
)
from .ma352 import BAUDRATES, DEFAULT_BAUDRATE, MA352, MA352Error, MA352Info

_LOGGER = logging.getLogger(__name__)


class CannotConnect(Exception):
    """Unable to open the port or no response."""


class WrongDevice(Exception):
    """Something answered, but it is not an MA352."""


async def validate_connection(url: str, baudrate: int) -> MA352Info:
    """Connect, query the unit and return its product info."""
    client = MA352(url, baudrate)
    try:
        await client.connect()
        await client.query()
    except MA352Error as err:
        raise CannotConnect(str(err)) from err
    finally:
        await client.disconnect()
    if not client.info.serial_number or not (client.info.model or "").startswith(MODEL):
        raise WrongDevice(client.info.model)
    return client.info


def _list_ports() -> list[SelectOptionDict]:
    ports = []
    for port in list_ports.comports():
        label = port.device
        if port.description and port.description != "n/a":
            label = f"{port.device} - {port.description}"
        ports.append(SelectOptionDict(value=port.device, label=label))
    return ports


def _schema(ports: list[SelectOptionDict], defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_SERIAL_PORT, default=defaults.get(CONF_SERIAL_PORT, vol.UNDEFINED)
            ): SelectSelector(
                SelectSelectorConfig(
                    options=ports,
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_BAUDRATE, default=str(defaults.get(CONF_BAUDRATE, DEFAULT_BAUDRATE))
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[str(rate) for rate in BAUDRATES],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


class MA352ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the McIntosh MA352."""

    VERSION = 1

    async def _async_try(
        self, user_input: dict[str, Any], errors: dict[str, str]
    ) -> tuple[dict[str, Any], MA352Info | None]:
        data = {
            CONF_SERIAL_PORT: user_input[CONF_SERIAL_PORT].strip(),
            CONF_BAUDRATE: int(user_input[CONF_BAUDRATE]),
        }
        try:
            info = await validate_connection(data[CONF_SERIAL_PORT], data[CONF_BAUDRATE])
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except WrongDevice:
            errors["base"] = "wrong_device"
        except Exception:
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return data, info
        return data, None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data, info = await self._async_try(user_input, errors)
            if info is not None:
                await self.async_set_unique_id(info.serial_number)
                self._abort_if_unique_id_configured(updates=data)
                return self.async_create_entry(
                    title=f"McIntosh {info.model} ({info.serial_number})", data=data
                )
            user_input = data

        ports = await self.hass.async_add_executor_job(_list_ports)
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(ports, user_input or {}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the port or baud rate of an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            # The running entry holds the port open (and serial servers often
            # accept a single client), so release it while validating.
            was_loaded = entry.state is ConfigEntryState.LOADED
            if was_loaded:
                await self.hass.config_entries.async_unload(entry.entry_id)
            data, info = await self._async_try(user_input, errors)
            if info is not None:
                await self.async_set_unique_id(info.serial_number)
                if self.unique_id == entry.unique_id:
                    return self.async_update_reload_and_abort(entry, data_updates=data)
                errors["base"] = "wrong_amplifier"
            if was_loaded:
                await self.hass.config_entries.async_reload(entry.entry_id)
            user_input = data

        ports = await self.hass.async_add_executor_job(_list_ports)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(ports, user_input or dict(entry.data)),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return MA352OptionsFlow()


class MA352OptionsFlow(OptionsFlow):
    """Options: volume limit."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_MAX_VOLUME: int(user_input[CONF_MAX_VOLUME])}
            )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MAX_VOLUME,
                        default=self.config_entry.options.get(
                            CONF_MAX_VOLUME, DEFAULT_MAX_VOLUME
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            max=100,
                            step=1,
                            unit_of_measurement="%",
                            mode=NumberSelectorMode.SLIDER,
                        )
                    ),
                }
            ),
        )

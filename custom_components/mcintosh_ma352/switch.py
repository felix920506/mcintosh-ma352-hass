"""Switches for the McIntosh MA352."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MA352ConfigEntry
from .entity import MA352Entity
from .hub import MA352Hub
from .ma352 import (
    CMD_DISPLAY_AUTO_OFF,
    CMD_EQUALIZER,
    CMD_HEADPHONE_HXD,
    CMD_HEADPHONES,
    CMD_METER_LIGHTS,
    CMD_MONO,
    CMD_OUTPUT_1,
    CMD_OUTPUT_2,
    CMD_TUBE_LIGHTS,
)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class MA352SwitchDescription(SwitchEntityDescription):
    """Describes an MA352 on/off setting."""

    command: str
    # Only usable while headphones are plugged in.
    needs_headphones: bool = False


SWITCHES: tuple[MA352SwitchDescription, ...] = (
    MA352SwitchDescription(key="output_1", translation_key="output_1", command=CMD_OUTPUT_1),
    MA352SwitchDescription(key="output_2", translation_key="output_2", command=CMD_OUTPUT_2),
    MA352SwitchDescription(key="equalizer", translation_key="equalizer", command=CMD_EQUALIZER),
    MA352SwitchDescription(key="mono", translation_key="mono", command=CMD_MONO),
    MA352SwitchDescription(
        key="headphone_hxd",
        translation_key="headphone_hxd",
        command=CMD_HEADPHONE_HXD,
        needs_headphones=True,
    ),
    MA352SwitchDescription(
        key="meter_lights",
        translation_key="meter_lights",
        command=CMD_METER_LIGHTS,
        entity_category=EntityCategory.CONFIG,
    ),
    MA352SwitchDescription(
        key="tube_lights",
        translation_key="tube_lights",
        command=CMD_TUBE_LIGHTS,
        entity_category=EntityCategory.CONFIG,
    ),
    MA352SwitchDescription(
        key="display_auto_off",
        translation_key="display_auto_off",
        command=CMD_DISPLAY_AUTO_OFF,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MA352ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switches."""
    hub = entry.runtime_data
    async_add_entities(MA352Switch(hub, description) for description in SWITCHES)


class MA352Switch(MA352Entity, SwitchEntity):
    """An on/off amplifier setting."""

    entity_description: MA352SwitchDescription

    def __init__(self, hub: MA352Hub, description: MA352SwitchDescription) -> None:
        """Initialize."""
        super().__init__(hub, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Return availability."""
        if not super().available:
            return False
        if self.entity_description.needs_headphones:
            return self.raw(CMD_HEADPHONES) == 1
        return self.raw(self.entity_description.command) is not None

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        value = self.raw(self.entity_description.command)
        return None if value is None else value == 1

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on."""
        await self.hub.async_command(self.entity_description.command, 1)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off."""
        await self.hub.async_command(self.entity_description.command, 0)

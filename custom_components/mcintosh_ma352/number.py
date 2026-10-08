"""Number entities (trim settings) for the McIntosh MA352."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import UnitOfSoundPressure
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MA352ConfigEntry
from .entity import MA352Entity
from .hub import MA352Hub
from .ma352 import CMD_BALANCE, CMD_INPUT_TRIM

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class MA352NumberDescription(NumberEntityDescription):
    """Describes an MA352 numeric setting."""

    command: str
    # native value = raw value * scale
    scale: float = 1


NUMBERS: tuple[MA352NumberDescription, ...] = (
    MA352NumberDescription(
        key="balance",
        translation_key="balance",
        command=CMD_BALANCE,
        native_min_value=-50,
        native_max_value=50,
        native_step=1,
        mode=NumberMode.SLIDER,
    ),
    MA352NumberDescription(
        key="input_trim",
        translation_key="input_trim",
        command=CMD_INPUT_TRIM,
        native_min_value=-6,
        native_max_value=6,
        native_step=0.5,
        scale=0.5,
        native_unit_of_measurement=UnitOfSoundPressure.DECIBEL,
        mode=NumberMode.SLIDER,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MA352ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up number entities."""
    hub = entry.runtime_data
    async_add_entities(MA352Number(hub, description) for description in NUMBERS)


class MA352Number(MA352Entity, NumberEntity):
    """A numeric amplifier setting."""

    entity_description: MA352NumberDescription

    def __init__(self, hub: MA352Hub, description: MA352NumberDescription) -> None:
        """Initialize."""
        super().__init__(hub, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Return availability."""
        return super().available and self.raw(self.entity_description.command) is not None

    @property
    def native_value(self) -> float | None:
        """Return the value."""
        raw = self.raw(self.entity_description.command)
        return None if raw is None else raw * self.entity_description.scale

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        raw = round(value / self.entity_description.scale)
        await self.hub.async_command(self.entity_description.command, raw)

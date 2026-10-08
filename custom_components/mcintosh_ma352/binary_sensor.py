"""Binary sensors for the McIntosh MA352."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MA352ConfigEntry
from .entity import MA352Entity
from .ma352 import CMD_HEADPHONES

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MA352ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    async_add_entities([MA352HeadphonesSensor(entry.runtime_data)])


class MA352HeadphonesSensor(MA352Entity, BinarySensorEntity):
    """Headphones plugged in."""

    _attr_translation_key = "headphones"

    def __init__(self, hub) -> None:
        """Initialize."""
        super().__init__(hub, "headphones")

    @property
    def available(self) -> bool:
        """Unavailable on units without a headphone jack (HPS 2)."""
        return super().available and self.value(CMD_HEADPHONES) in (0, 1)

    @property
    def is_on(self) -> bool | None:
        """Return True when headphones are plugged in."""
        value = self.value(CMD_HEADPHONES)
        return None if value is None else value == 1

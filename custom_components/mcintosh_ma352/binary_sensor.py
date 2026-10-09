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
    hub = entry.runtime_data
    async_add_entities([MA352HeadphonesSensor(hub), MA352PassthroughSensor(hub)])


class MA352HeadphonesSensor(MA352Entity, BinarySensorEntity):
    """Headphones plugged in."""

    _attr_translation_key = "headphones"

    def __init__(self, hub) -> None:
        """Initialize."""
        super().__init__(hub, "headphones")

    @property
    def available(self) -> bool:
        """Unavailable on units without a headphone jack (HPS 2)."""
        return super().available and self.raw(CMD_HEADPHONES) in (0, 1)

    @property
    def is_on(self) -> bool | None:
        """Return True when headphones are plugged in."""
        value = self.raw(CMD_HEADPHONES)
        return None if value is None else value == 1


class MA352PassthroughSensor(MA352Entity, BinarySensorEntity):
    """Passthrough (power amplifier only, fixed gain) mode.

    Inferred from volume reports; the unit has no status for it.
    """

    _attr_translation_key = "passthrough"

    def __init__(self, hub) -> None:
        """Initialize."""
        super().__init__(hub, "passthrough")

    @property
    def is_on(self) -> bool | None:
        """Return True in passthrough mode, None if undeterminable."""
        return self.hub.client.state.passthrough

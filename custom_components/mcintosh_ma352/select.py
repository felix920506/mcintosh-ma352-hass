"""Select entities for the McIntosh MA352."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MA352ConfigEntry
from .entity import MA352Entity
from .hub import MA352Hub
from .ma352 import (
    CMD_DISPLAY_BRIGHTNESS,
    CMD_INPUT,
    CMD_PHONO_CAPACITANCE,
    DISPLAY_BRIGHTNESS,
    PHONO_CAPACITANCE,
    PHONO_INPUT,
)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class MA352SelectDescription(SelectEntityDescription):
    """Describes an MA352 enumerated setting."""

    command: str
    # raw value -> option label
    values: dict[int, str]
    # Only usable while the phono input is selected.
    needs_phono: bool = False


SELECTS: tuple[MA352SelectDescription, ...] = (
    MA352SelectDescription(
        key="display_brightness",
        translation_key="display_brightness",
        command=CMD_DISPLAY_BRIGHTNESS,
        values={raw: f"{pct}%" for raw, pct in DISPLAY_BRIGHTNESS.items()},
        entity_category=EntityCategory.CONFIG,
    ),
    MA352SelectDescription(
        key="phono_capacitance",
        translation_key="phono_capacitance",
        command=CMD_PHONO_CAPACITANCE,
        values={raw: f"{pf} pF" for raw, pf in PHONO_CAPACITANCE.items()},
        needs_phono=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MA352ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up select entities."""
    hub = entry.runtime_data
    async_add_entities(MA352Select(hub, description) for description in SELECTS)


class MA352Select(MA352Entity, SelectEntity):
    """An enumerated amplifier setting."""

    entity_description: MA352SelectDescription

    def __init__(self, hub: MA352Hub, description: MA352SelectDescription) -> None:
        """Initialize."""
        super().__init__(hub, description.key)
        self.entity_description = description
        self._attr_options = list(description.values.values())
        self._option_to_raw = {label: raw for raw, label in description.values.items()}

    @property
    def available(self) -> bool:
        """Return availability."""
        if not super().available:
            return False
        if self.entity_description.needs_phono and self.value(CMD_INPUT) != PHONO_INPUT:
            return False
        return self.value(self.entity_description.command) is not None

    @property
    def current_option(self) -> str | None:
        """Return the selected option."""
        return self.entity_description.values.get(
            self.value(self.entity_description.command)
        )

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        await self.hub.async_command(
            self.entity_description.command, self._option_to_raw[option]
        )

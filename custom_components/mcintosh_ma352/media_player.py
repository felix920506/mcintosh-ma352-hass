"""Media player for the McIntosh MA352."""

from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MA352ConfigEntry
from .const import CONF_MAX_VOLUME, DEFAULT_MAX_VOLUME
from .entity import MA352Entity
from .ma352 import CMD_INPUT, CMD_MUTE, CMD_POWER, CMD_VOLUME, INPUTS

PARALLEL_UPDATES = 0

SOURCE_TO_INPUT = {name: index for index, name in INPUTS.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MA352ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the media player."""
    max_volume = entry.options.get(CONF_MAX_VOLUME, DEFAULT_MAX_VOLUME)
    async_add_entities([MA352MediaPlayer(entry.runtime_data, max_volume)])


class MA352MediaPlayer(MA352Entity, MediaPlayerEntity):
    """The amplifier itself."""

    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.RECEIVER
    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )
    _attr_source_list = list(INPUTS.values())
    _requires_power = False

    def __init__(self, hub, max_volume: int) -> None:
        """Initialize."""
        super().__init__(hub, "media_player")
        self._max_volume = max_volume

    @property
    def state(self) -> MediaPlayerState:
        """Return the power state."""
        return MediaPlayerState.ON if self.hub.client.state.power else MediaPlayerState.OFF

    @property
    def _on(self) -> bool:
        return self.hub.client.state.power

    @property
    def volume_level(self) -> float | None:
        """Volume 0..1."""
        volume = self.value(CMD_VOLUME)
        return volume / 100 if self._on and volume is not None else None

    @property
    def is_volume_muted(self) -> bool | None:
        """Mute state."""
        mute = self.value(CMD_MUTE)
        return mute == 1 if self._on and mute is not None else None

    @property
    def source(self) -> str | None:
        """Current input."""
        return INPUTS.get(self.value(CMD_INPUT)) if self._on else None

    @property
    def extra_state_attributes(self) -> dict[str, int]:
        """Expose the configured volume limit."""
        return {"max_volume": self._max_volume}

    async def async_turn_on(self) -> None:
        """Power on."""
        await self.hub.async_command(CMD_POWER, 1)

    async def async_turn_off(self) -> None:
        """Power off (standby)."""
        await self.hub.async_command(CMD_POWER, 0)

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume, clamped to the configured maximum."""
        level = max(0, min(round(volume * 100), self._max_volume))
        await self.hub.async_command(CMD_VOLUME, level)

    async def async_volume_up(self) -> None:
        """Volume up 1%, unless that exceeds the configured maximum."""
        current = self.value(CMD_VOLUME)
        if current is not None and current >= self._max_volume:
            return
        await self.hub.async_command(CMD_VOLUME, "U")

    async def async_volume_down(self) -> None:
        """Volume down 1%."""
        await self.hub.async_command(CMD_VOLUME, "D")

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute."""
        await self.hub.async_command(CMD_MUTE, 1 if mute else 0)

    async def async_select_source(self, source: str) -> None:
        """Select an input."""
        await self.hub.async_command(CMD_INPUT, SOURCE_TO_INPUT[source])

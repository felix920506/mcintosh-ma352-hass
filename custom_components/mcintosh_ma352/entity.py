"""Base entity for the McIntosh MA352 integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, MANUFACTURER, MODEL
from .hub import MA352Hub


class MA352Entity(Entity):
    """Entity backed by an MA352 hub; most features need the amp powered on."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    # Entities whose command returns "Invalid Command" in standby.
    _requires_power = True

    def __init__(self, hub: MA352Hub, key: str) -> None:
        """Initialize."""
        self.hub = hub
        info = hub.client.info
        self._attr_unique_id = f"{hub.unique_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.unique_id)},
            manufacturer=MANUFACTURER,
            model=info.model or MODEL,
            name=f"{MANUFACTURER} {info.model or MODEL}",
            serial_number=info.serial_number,
            sw_version=info.firmware,
        )

    @property
    def available(self) -> bool:
        """Return availability."""
        if not self.hub.available:
            return False
        return not self._requires_power or self.hub.client.state.power

    def raw(self, name: str) -> int | None:
        """Return a raw state value."""
        return self.hub.client.state.get(name)

    async def async_added_to_hass(self) -> None:
        """Subscribe to updates."""
        self.async_on_remove(self.hub.add_listener(self.async_write_ha_state))

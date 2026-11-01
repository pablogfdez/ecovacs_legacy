"""Base entity for legacy Ecovacs robots."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .device import LegacyDevice


class LegacyEntity(Entity):
    """Entity bound to a legacy robot."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, device: LegacyDevice) -> None:
        """Initialize the entity."""
        self.device = device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.did)},
            manufacturer="Ecovacs",
            model=device.model,
            name=device.name,
            serial_number=device.did,
        )

    @property
    def available(self) -> bool:
        """Return True if the XMPP connection is up."""
        return self.device.available

    async def async_added_to_hass(self) -> None:
        """Subscribe to device updates."""
        self.async_on_remove(self.device.add_listener(self.async_write_ha_state))

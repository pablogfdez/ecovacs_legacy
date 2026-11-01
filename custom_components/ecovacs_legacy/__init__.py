"""Ecovacs Legacy (XMPP) integration for Deebot OZMO 930 and similar robots."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .controller import LegacyController

PLATFORMS = [Platform.SENSOR, Platform.VACUUM]

type LegacyConfigEntry = ConfigEntry[LegacyController]


async def async_setup_entry(hass: HomeAssistant, entry: LegacyConfigEntry) -> bool:
    """Set up the integration from a config entry."""
    controller = LegacyController(hass, entry)
    entry.async_on_unload(controller.teardown)
    await controller.initialize()
    entry.runtime_data = controller
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LegacyConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

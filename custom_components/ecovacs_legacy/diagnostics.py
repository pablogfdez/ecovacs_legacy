"""Diagnostics for Ecovacs Legacy."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import LegacyConfigEntry

TO_REDACT = {
    "username",
    "password",
    "device_id",
    "account_credentials",
    "did",
    "nick",
    "mac",
    "ip",
    "wifi_ssid",
    "resource",
    "uid",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LegacyConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    return {
        "config": async_redact_data(dict(entry.data), TO_REDACT),
        "devices": [
            {
                "info": async_redact_data(device.info, TO_REDACT),
                "connected": device.client.connected,
                "state": async_redact_data(asdict(device.state), TO_REDACT),
            }
            for device in entry.runtime_data.devices
        ],
    }

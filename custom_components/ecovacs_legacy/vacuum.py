"""Vacuum entity for legacy Ecovacs robots."""

from __future__ import annotations

from typing import Any

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LegacyConfigEntry, protocol
from .device import LegacyDevice
from .entity import LegacyEntity

ACTIVITIES = {
    "cleaning": VacuumActivity.CLEANING,
    "paused": VacuumActivity.PAUSED,
    "returning": VacuumActivity.RETURNING,
    "docked": VacuumActivity.DOCKED,
    "idle": VacuumActivity.IDLE,
    "error": VacuumActivity.ERROR,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LegacyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the vacuum entities."""
    async_add_entities(LegacyVacuum(d) for d in entry.runtime_data.devices)


class LegacyVacuum(LegacyEntity, StateVacuumEntity):
    """Legacy Ecovacs vacuum."""

    _attr_name = None
    _attr_fan_speed_list = list(protocol.FAN_SPEEDS)
    _attr_supported_features = (
        VacuumEntityFeature.START
        | VacuumEntityFeature.PAUSE
        | VacuumEntityFeature.STOP
        | VacuumEntityFeature.RETURN_HOME
        | VacuumEntityFeature.CLEAN_SPOT
        | VacuumEntityFeature.LOCATE
        | VacuumEntityFeature.FAN_SPEED
        | VacuumEntityFeature.SEND_COMMAND
        | VacuumEntityFeature.STATE
    )

    def __init__(self, device: LegacyDevice) -> None:
        """Initialize the vacuum."""
        super().__init__(device)
        self._attr_unique_id = device.did

    @property
    def activity(self) -> VacuumActivity | None:
        """Return the activity."""
        return ACTIVITIES[self.device.state.vacuum_state]

    @property
    def fan_speed(self) -> str | None:
        """Return the suction power."""
        return self.device.state.fan_speed

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        state = self.device.state
        return {
            "error": state.error_text or None,
            "error_code": state.error_code,
            "water_level": state.water_level,
            "water_box_installed": state.water_box,
        }

    async def async_start(self) -> None:
        """Start or resume cleaning."""
        if self.device.state.vacuum_state == "paused":
            await self.device.send(protocol.resume())
        else:
            await self.device.send(
                protocol.clean(speed=self.device.state.fan_speed or "standard")
            )

    async def async_pause(self) -> None:
        """Pause cleaning."""
        await self.device.send(protocol.pause())

    async def async_stop(self, **kwargs: Any) -> None:
        """Stop cleaning."""
        await self.device.send(protocol.stop())

    async def async_return_to_base(self, **kwargs: Any) -> None:
        """Return to the dock."""
        await self.device.send(protocol.charge())

    async def async_clean_spot(self, **kwargs: Any) -> None:
        """Clean a spot."""
        await self.device.send(protocol.clean("spot"))

    async def async_locate(self, **kwargs: Any) -> None:
        """Play a sound."""
        await self.device.send(protocol.play_sound())

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        """Set the suction power."""
        await self.device.send(protocol.set_clean_speed(fan_speed))

    async def async_send_command(
        self,
        command: str,
        params: dict[str, Any] | list[Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Send a command.

        Friendly commands: ``spot_area`` (areas), ``custom_area`` (coordinates,
        passes), ``edge``, ``set_water_level`` (level). Anything else is sent as
        a raw ``<ctl td="command" ...params/>``.
        """
        params = params if isinstance(params, dict) else {}
        if command == "spot_area":
            cmd = protocol.spot_area(str(params["areas"]))
        elif command == "custom_area":
            cmd = protocol.custom_area(
                str(params["coordinates"]), int(params.get("passes", 1))
            )
        elif command == "edge":
            cmd = protocol.clean("edge")
        elif command == "set_water_level":
            cmd = protocol.set_water_level(int(params["level"]))
        else:
            cmd = protocol.raw(command, params)
        await self.device.send(cmd)

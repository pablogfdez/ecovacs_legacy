"""Sensors for legacy Ecovacs robots."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfArea, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LegacyConfigEntry
from .device import LegacyDevice
from .entity import LegacyEntity
from .protocol import RobotState


@dataclass(kw_only=True, frozen=True)
class LegacySensorDescription(SensorEntityDescription):
    """Sensor description with a value function."""

    value_fn: Callable[[RobotState], str | int | None]


def _lifespan(component: str) -> LegacySensorDescription:
    return LegacySensorDescription(
        key=f"lifespan_{component}",
        translation_key=f"lifespan_{component}",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.lifespan.get(component),
    )


SENSORS: tuple[LegacySensorDescription, ...] = (
    LegacySensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.battery,
    ),
    LegacySensorDescription(
        key="cleaned_area",
        translation_key="cleaned_area",
        native_unit_of_measurement=UnitOfArea.SQUARE_METERS,
        device_class=SensorDeviceClass.AREA,
        value_fn=lambda s: s.cleaned_area,
    ),
    LegacySensorDescription(
        key="cleaned_time",
        translation_key="cleaned_time",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda s: s.cleaned_seconds,
    ),
    LegacySensorDescription(
        key="total_area",
        translation_key="total_area",
        native_unit_of_measurement=UnitOfArea.SQUARE_METERS,
        device_class=SensorDeviceClass.AREA,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.total_area,
    ),
    LegacySensorDescription(
        key="total_time",
        translation_key="total_time",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        suggested_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.total_seconds,
    ),
    LegacySensorDescription(
        key="total_count",
        translation_key="total_count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.total_count,
    ),
    LegacySensorDescription(
        key="water_level",
        translation_key="water_level",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.water_level,
    ),
    LegacySensorDescription(
        key="error",
        translation_key="error",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.error_text or None,
    ),
    LegacySensorDescription(
        key="ip",
        translation_key="ip",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.ip,
    ),
    LegacySensorDescription(
        key="wifi_ssid",
        translation_key="wifi_ssid",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.wifi_ssid,
    ),
    _lifespan("main_brush"),
    _lifespan("side_brush"),
    _lifespan("filter"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LegacyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    async_add_entities(
        LegacySensor(device, description)
        for device in entry.runtime_data.devices
        for description in SENSORS
    )


class LegacySensor(LegacyEntity, SensorEntity):
    """Sensor of a legacy robot."""

    entity_description: LegacySensorDescription

    def __init__(
        self, device: LegacyDevice, description: LegacySensorDescription
    ) -> None:
        """Initialize the sensor."""
        super().__init__(device)
        self.entity_description = description
        self._attr_unique_id = f"{device.did}_{description.key}"

    @property
    def native_value(self) -> str | int | None:
        """Return the value."""
        return self.entity_description.value_fn(self.device.state)

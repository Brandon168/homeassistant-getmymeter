"""Sensor entities for GetMyMeter."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import override
from zoneinfo import ZoneInfo

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import API_ORIGIN, DOMAIN, INTEGRATION_TITLE
from .coordinator import (
    GetMyMeterConfigEntry,
    GetMyMeterCoordinator,
    GetMyMeterData,
)
from .identity import stable_entry_unique_id
from .parser import UsageRecord


@dataclass(frozen=True, kw_only=True)
class GetMyMeterSensorDescription(SensorEntityDescription):
    """Describe one water-usage sensor."""

    value_fn: Callable[[GetMyMeterData], float | None]
    record_fn: Callable[[GetMyMeterData], UsageRecord | None]


SENSOR_DESCRIPTIONS: tuple[GetMyMeterSensorDescription, ...] = (
    GetMyMeterSensorDescription(
        key="raw_usage",
        translation_key="raw_usage",
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: (
            data.latest_raw.usage_gallons if data.latest_raw else None
        ),
        record_fn=lambda data: data.latest_raw,
    ),
    GetMyMeterSensorDescription(
        key="daily_usage",
        translation_key="daily_usage",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        value_fn=lambda data: (
            data.latest_daily.usage_gallons if data.latest_daily else None
        ),
        record_fn=lambda data: data.latest_daily,
    ),
    GetMyMeterSensorDescription(
        key="cumulative_usage",
        translation_key="cumulative_usage",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: (
            data.latest_daily.cumulative_gallons if data.latest_daily else None
        ),
        record_fn=lambda data: data.latest_daily,
    ),
    GetMyMeterSensorDescription(
        key="monthly_usage",
        translation_key="monthly_usage",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        value_fn=lambda data: (
            data.latest_monthly.usage_gallons if data.latest_monthly else None
        ),
        record_fn=lambda data: data.latest_monthly,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GetMyMeterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up GetMyMeter sensors from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        GetMyMeterSensor(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
    )


class GetMyMeterSensor(CoordinatorEntity[GetMyMeterCoordinator], SensorEntity):
    """Represent one GetMyMeter usage value."""

    _attr_attribution = "Data provided by GetMyMeter / H2O Analytics"
    _attr_has_entity_name = True
    entity_description: GetMyMeterSensorDescription

    def __init__(
        self,
        coordinator: GetMyMeterCoordinator,
        description: GetMyMeterSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        entry = coordinator.config_entry
        stable_id = entry.unique_id or stable_entry_unique_id(entry.data)
        self._attr_unique_id = f"{stable_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, stable_entry_unique_id(entry.data))},
            manufacturer="H2O Analytics",
            model="AMI water meter",
            name=INTEGRATION_TITLE,
            configuration_url=API_ORIGIN,
        )

    @property
    @override
    def native_value(self) -> float | None:
        """Return the latest usage value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    @override
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Expose only non-secret sample metadata."""
        record = self.entity_description.record_fn(self.coordinator.data)
        if record is None:
            return None
        return {
            "bucket": record.bucket,
            "sample_timestamp": record.timestamp_in(
                ZoneInfo(self.coordinator.hass.config.time_zone)
            ).isoformat(),
        }

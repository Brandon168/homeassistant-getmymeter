"""Sensor setup and stable entity identifier tests."""

from datetime import UTC, datetime

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.core import HomeAssistant

from custom_components.getmymeter.const import BUCKET_DAILY, BUCKET_MONTHLY, BUCKET_RAW
from custom_components.getmymeter.coordinator import (
    GetMyMeterCoordinator,
    GetMyMeterData,
)
from custom_components.getmymeter.identity import stable_entry_unique_id
from custom_components.getmymeter.parser import UsageRecord
from custom_components.getmymeter.sensor import SENSOR_DESCRIPTIONS, GetMyMeterSensor

from .conftest import make_entry


@pytest.mark.asyncio
async def test_four_current_water_sensors_have_stable_ids(
    hass: HomeAssistant,
) -> None:
    """Raw, daily, cumulative, and monthly entities use the hashed identity."""
    entry = make_entry()
    entry.add_to_hass(hass)
    coordinator = GetMyMeterCoordinator(hass, entry, object())
    coordinator.data = GetMyMeterData(
        raw=(UsageRecord(1704067200000, BUCKET_RAW, 1, 10, None),),
        daily=(UsageRecord(1704067200000, BUCKET_DAILY, 2, 10, None),),
        monthly=(UsageRecord(1704067200000, BUCKET_MONTHLY, 3, 10, None),),
    )
    entities = [
        GetMyMeterSensor(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
    ]
    prefix = stable_entry_unique_id(entry.data)
    assert len(entities) == 4
    assert {entity.unique_id for entity in entities} == {
        f"{prefix}_{description.key}" for description in SENSOR_DESCRIPTIONS
    }
    assert all(entry.entry_id not in entity.unique_id for entity in entities)
    assert entities[0].native_value == 1
    assert entities[0].extra_state_attributes == {
        "bucket": BUCKET_RAW,
        "sample_timestamp": datetime.fromtimestamp(1704067200, UTC).isoformat(),
    }
    assert entities[2].native_value == 10
    assert entities[0].device_info["identifiers"] == {
        ("getmymeter", stable_entry_unique_id(entry.data))
    }
    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}
    assert descriptions["raw_usage"].device_class is None
    assert descriptions["raw_usage"].state_class is SensorStateClass.MEASUREMENT
    assert descriptions["daily_usage"].device_class is SensorDeviceClass.WATER
    assert descriptions["daily_usage"].state_class is None
    assert (
        descriptions["cumulative_usage"].state_class
        is SensorStateClass.TOTAL_INCREASING
    )
    assert descriptions["monthly_usage"].device_class is SensorDeviceClass.WATER
    assert descriptions["monthly_usage"].state_class is None

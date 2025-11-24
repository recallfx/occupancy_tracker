"""Platform setup for Occupancy Tracker sensors."""

from .helpers.types import OccupancyTrackerConfig
from .const import DOMAIN
from .sensors import (
    AnomalySensor,
    OccupancyCountSensor,
    OccupancyProbabilitySensor,
    OccupiedInsideAreasSensor,
    OccupiedOutsideAreasSensor,
    TotalOccupantsInsideSensor,
    TotalOccupantsOutsideSensor,
    TotalOccupantsSensor,
)


async def async_setup_platform(
    hass,
    config: OccupancyTrackerConfig,
    async_add_entities,
    discovery_info=None,
):
    """Set up the Occupancy Tracker sensors."""
    coordinator = hass.data[DOMAIN]["coordinator"]
    sensors = []

    # Individual area sensors
    for area in coordinator.config["areas"]:
        sensors.append(OccupancyCountSensor(coordinator, area))
        sensors.append(OccupancyProbabilitySensor(coordinator, area))

    # Global sensors
    sensors.extend(
        [
            OccupiedInsideAreasSensor(coordinator),
            OccupiedOutsideAreasSensor(coordinator),
            TotalOccupantsInsideSensor(coordinator),
            TotalOccupantsOutsideSensor(coordinator),
            TotalOccupantsSensor(coordinator),
            AnomalySensor(coordinator),
        ]
    )

    async_add_entities(sensors, True)

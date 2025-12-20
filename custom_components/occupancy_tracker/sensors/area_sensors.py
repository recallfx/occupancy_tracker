"""Sensors for individual area tracking."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..coordinator import OccupancyCoordinator


class OccupancyCountSensor(CoordinatorEntity, SensorEntity):
    """Sensor for occupancy count."""

    def __init__(self, coordinator: OccupancyCoordinator, area: str):
        super().__init__(coordinator)
        self._area = area
        self._attr_name = f"Occupancy Count {area}"
        self._attr_unique_id = f"occupancy_count_{area}"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self.coordinator.get_occupancy(self._area)


class OccupancyProbabilitySensor(CoordinatorEntity, SensorEntity):
    """Sensor for occupancy probability."""

    def __init__(self, coordinator: OccupancyCoordinator, area: str):
        super().__init__(coordinator)
        self._area = area
        self._attr_name = f"Occupancy Probability {area}"
        self._attr_unique_id = f"occupancy_probability_{area}"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self.coordinator.get_occupancy_probability(self._area)

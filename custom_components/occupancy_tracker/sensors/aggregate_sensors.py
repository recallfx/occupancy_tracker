"""Sensors for aggregate occupancy statistics."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..coordinator import OccupancyCoordinator


class TotalOccupantsInsideSensor(CoordinatorEntity, SensorEntity):
    """Sensor for total number of occupants inside."""

    def __init__(self, coordinator: OccupancyCoordinator):
        super().__init__(coordinator)
        self._attr_name = "Total Occupants Inside"
        self._attr_unique_id = "total_occupants_inside"

    @property
    def state(self):
        """Return the total number of occupants in indoor areas."""
        return sum(
            self.coordinator.get_occupancy(area)
            for area, config in self.coordinator.config["areas"].items()
            if config.get("indoors", True)
        )


class TotalOccupantsOutsideSensor(CoordinatorEntity, SensorEntity):
    """Sensor for total number of occupants outside."""

    def __init__(self, coordinator: OccupancyCoordinator):
        super().__init__(coordinator)
        self._attr_name = "Total Occupants Outside"
        self._attr_unique_id = "total_occupants_outside"

    @property
    def state(self):
        """Return the total number of occupants in outdoor areas."""
        return sum(
            self.coordinator.get_occupancy(area)
            for area, config in self.coordinator.config["areas"].items()
            if not config.get("indoors", True)
        )


class TotalOccupantsSensor(CoordinatorEntity, SensorEntity):
    """Sensor for total number of occupants in the system."""

    def __init__(self, coordinator: OccupancyCoordinator):
        super().__init__(coordinator)
        self._attr_name = "Total Occupants"
        self._attr_unique_id = "total_occupants"

    @property
    def state(self):
        """Return the total number of occupants in all areas."""
        return sum(
            self.coordinator.get_occupancy(area)
            for area in self.coordinator.config["areas"]
        )

"""Sensors for location-based occupancy (inside/outside areas)."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..coordinator import OccupancyCoordinator


class OccupiedInsideAreasSensor(CoordinatorEntity, SensorEntity):
    """Sensor that lists all occupied indoor areas."""

    def __init__(self, coordinator: OccupancyCoordinator):
        super().__init__(coordinator)
        self._attr_name = "Occupied Inside Areas"
        self._attr_unique_id = "occupied_inside_areas"

    @property
    def state(self):
        """Return the number of occupied indoor areas."""
        occupied_areas = [
            area
            for area, config in self.coordinator.config["areas"].items()
            if config.get("indoors", True)
            and self.coordinator.get_occupancy(area) > 0
        ]
        return len(occupied_areas)

    @property
    def extra_state_attributes(self):
        """Return the list of occupied indoor areas."""
        return {
            "areas": [
                area
                for area, config in self.coordinator.config["areas"].items()
                if config.get("indoors", True)
                and self.coordinator.get_occupancy(area) > 0
            ]
        }


class OccupiedOutsideAreasSensor(CoordinatorEntity, SensorEntity):
    """Sensor that lists all occupied outdoor areas."""

    def __init__(self, coordinator: OccupancyCoordinator):
        super().__init__(coordinator)
        self._attr_name = "Occupied Outside Areas"
        self._attr_unique_id = "occupied_outside_areas"

    @property
    def state(self):
        """Return the number of occupied outdoor areas."""
        occupied_areas = [
            area
            for area, config in self.coordinator.config["areas"].items()
            if not config.get("indoors", True)
            and self.coordinator.get_occupancy(area) > 0
        ]
        return len(occupied_areas)

    @property
    def extra_state_attributes(self):
        """Return the list of occupied outdoor areas."""
        return {
            "areas": [
                area
                for area, config in self.coordinator.config["areas"].items()
                if not config.get("indoors", True)
                and self.coordinator.get_occupancy(area) > 0
            ]
        }

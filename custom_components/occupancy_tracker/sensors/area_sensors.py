"""Binary sensor for individual area occupancy."""

import time

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..coordinator import OccupancyCoordinator


class AreaOccupancyBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor that is ON when an area is occupied.

    Attributes expose count, probability, and last_motion for debugging.
    """

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(self, coordinator: OccupancyCoordinator, area: str):
        super().__init__(coordinator)
        self._area = area
        area_name = coordinator.config["areas"][area].get("name", area)
        self._attr_name = f"{area_name} Occupancy"
        self._attr_unique_id = f"occupancy_{area}"

    @property
    def is_on(self) -> bool:
        """Return True if area is occupied."""
        return self.coordinator.get_occupancy(self._area) > 0

    @property
    def extra_state_attributes(self):
        """Return count, probability, and last motion as attributes."""
        area_state = self.coordinator.areas.get(self._area)
        if not area_state:
            return {}

        now = time.time()
        probability = self.coordinator.get_occupancy_probability(self._area, now)
        last_motion = area_state.last_motion
        time_since = round(now - last_motion) if last_motion > 0 else None

        return {
            "occupancy_count": area_state.occupancy,
            "probability": round(probability, 2),
            "last_motion": last_motion if last_motion > 0 else None,
            "time_since_motion_s": time_since,
            "is_indoors": area_state.is_indoors,
            "is_exit_capable": area_state.is_exit_capable,
        }

"""Platform setup for Occupancy Tracker binary sensors."""

from .const import DOMAIN
from .sensors import AreaOccupancyBinarySensor


async def async_setup_platform(
    hass,
    config,
    async_add_entities,
    discovery_info=None,
):
    """Set up the Occupancy Tracker binary sensors."""
    coordinator = hass.data[DOMAIN]["coordinator"]

    entities = [
        AreaOccupancyBinarySensor(coordinator, area)
        for area in coordinator.config["areas"]
    ]

    async_add_entities(entities, True)

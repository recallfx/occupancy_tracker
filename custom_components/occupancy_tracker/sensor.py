"""Platform setup for Occupancy Tracker sensors."""

from .const import DOMAIN
from .sensors import AnomalySensor


async def async_setup_platform(
    hass,
    config,
    async_add_entities,
    discovery_info=None,
):
    """Set up the Occupancy Tracker sensors."""
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities([AnomalySensor(coordinator)], True)

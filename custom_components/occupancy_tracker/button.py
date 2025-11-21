"""Button platform for resetting anomaly detection."""

from homeassistant.components.button import ButtonEntity
from .const import DOMAIN


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the Occupancy Tracker button platform."""
    coordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities([ResetAnomaliesButton(coordinator)], True)


class ResetAnomaliesButton(ButtonEntity):
    """Button entity to reset anomaly detection."""

    def __init__(self, coordinator):
        self._coordinator = coordinator
        self._attr_name = "Reset Anomalies"
        self._attr_unique_id = "reset_anomalies_button"

    async def async_press(self) -> None:
        """Handle the button press - reset anomalies."""
        self._coordinator.reset_anomalies()

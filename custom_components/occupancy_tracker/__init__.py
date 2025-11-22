"""The occupancy_tracker integration."""

import logging
import time

import voluptuous as vol

from homeassistant.core import Event, HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from datetime import timedelta

from .const import DOMAIN
from .helpers.types import OccupancyTrackerConfig
from .coordinator import OccupancyCoordinator

_LOGGER = logging.getLogger(__name__)

# Schema for individual sensor configuration
SENSOR_SCHEMA = vol.Schema(
    {
        vol.Required("area"): vol.Any(cv.string, [cv.string]),
        vol.Optional("type", default="motion"): cv.string,
    }
)

# Schema for individual area configuration
AREA_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Optional("exit_capable", default=False): cv.boolean,
    }
)

# Main configuration schema
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required("areas"): vol.Schema({cv.string: AREA_SCHEMA}),
                vol.Required("adjacency"): vol.Schema({cv.string: [cv.string]}),
                vol.Required("sensors"): vol.Schema({cv.entity_id: SENSOR_SCHEMA}),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Occupancy Tracker integration from YAML configuration."""
    conf = config.get(DOMAIN)
    if conf is None:
        _LOGGER.error("No configuration found for occupancy_tracker")
        return False

    # Build the occupancy system configuration from HA's YAML configuration.
    occupancy_config: OccupancyTrackerConfig = {
        "areas": conf.get("areas", {}),
        "adjacency": conf.get("adjacency", {}),
        "sensors": conf.get("sensors", {}),
    }

    # Validate configuration
    if not _validate_config(occupancy_config):
        return False

    # Create the coordinator instance.
    coordinator = OccupancyCoordinator(hass, occupancy_config)
    
    # Store the coordinator
    hass.data[DOMAIN] = {"coordinator": coordinator}

    async def state_change_listener(event: Event) -> None:
        """Handle state changes for sensors."""
        # Since sensor names are assumed to be the actual HA entity IDs,
        # check if the changed entity is one of our sensors.
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")

        sensors = occupancy_config.get("sensors", {})
        if entity_id in sensors:
            # Handle sensor unavailability
            if new_state is None or new_state.state in ["unavailable", "unknown"]:
                _LOGGER.warning(
                    f"Sensor {entity_id} is unavailable or in unknown state, skipping event"
                )
                return

            # Interpret HA state: 'on' becomes True; any other value is False
            sensor_state = new_state.state.lower() == "on"
            timestamp = time.time()
            
            # Process event through coordinator
            coordinator.process_sensor_event(
                entity_id, sensor_state, timestamp=timestamp
            )

    # Set up state listeners for each sensor entity defined in the occupancy config.
    sensor_entities = list(occupancy_config.get("sensors", {}).keys())
    if sensor_entities:
        async_track_state_change_event(hass, sensor_entities, state_change_listener)

    # Set up periodic check for timeouts (every 60 seconds)
    async def interval_listener(now) -> None:
        """Handle periodic checks."""
        coordinator.check_timeouts(timestamp=now.timestamp())

    remove_interval = async_track_time_interval(hass, interval_listener, timedelta(seconds=60))
    hass.data[DOMAIN]["remove_update_listener"] = remove_interval

    # Ensure timer is cleaned up when HA stops
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP
    
    async def _cleanup_timer(event):
        remove_interval()
        
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _cleanup_timer)

    # Set up the sensor platform
    await async_load_platform(hass, "sensor", DOMAIN, {}, config)

    # Set up the button platform
    await async_load_platform(hass, "button", DOMAIN, {}, config)

    _LOGGER.info("Occupancy Tracker integration set up successfully")
    return True


def _validate_config(config: OccupancyTrackerConfig) -> bool:
    """Validate that all referenced areas exist."""
    areas = config.get("areas", {})
    adjacency = config.get("adjacency", {})
    sensors = config.get("sensors", {})
    
    # Validate adjacency
    for area_id, adjacent_areas in adjacency.items():
        if area_id not in areas:
            _LOGGER.error(f"Adjacency config references unknown area: {area_id}")
            return False
        for adj_id in adjacent_areas:
            if adj_id not in areas:
                _LOGGER.error(f"Adjacency config for {area_id} references unknown area: {adj_id}")
                return False
                
    # Validate sensors
    for sensor_id, sensor_config in sensors.items():
        area_config = sensor_config.get("area")
        if area_config:
            area_ids = area_config if isinstance(area_config, list) else [area_config]
            for area_id in area_ids:
                if area_id not in areas:
                    _LOGGER.error(f"Sensor {sensor_id} references unknown area: {area_id}")
                    return False
                
        # Validate between_areas for magnetic sensors
        if sensor_config.get("type") == "magnetic":
            between = sensor_config.get("between_areas")
            if between:
                for area_id in between:
                    if area_id not in areas:
                        _LOGGER.error(f"Sensor {sensor_id} between_areas references unknown area: {area_id}")
                        return False

    return True

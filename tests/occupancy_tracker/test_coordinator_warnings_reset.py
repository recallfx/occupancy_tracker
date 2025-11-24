"""Tests for coordinator warning and reset functionality."""

import time
from unittest.mock import Mock

from homeassistant.core import HomeAssistant
from custom_components.occupancy_tracker.coordinator import OccupancyCoordinator


class TestOccupancyCoordinatorWarnings:
    """Test warning management."""

    def test_get_warnings(self):
        """Test getting warnings from coordinator."""
        hass = Mock(spec=HomeAssistant)
        config = {"areas": {}, "adjacency": {}, "sensors": {}}

        coordinator = OccupancyCoordinator(hass, config)

        # Initially no warnings
        assert len(coordinator.get_warnings()) == 0

    def test_resolve_warning(self):
        """Test resolving a warning."""
        hass = Mock(spec=HomeAssistant)
        config = {"areas": {}, "adjacency": {}, "sensors": {}}

        coordinator = OccupancyCoordinator(hass, config)

        # Create a warning
        warning = coordinator.anomaly_detector._create_warning("test", "Test warning")

        result = coordinator.resolve_warning(warning.id)

        assert result is True
        assert warning.is_active is False


class TestOccupancyCoordinatorReset:
    """Test reset functionality."""

    def test_reset(self):
        """Test full system reset."""
        hass = Mock(spec=HomeAssistant)
        config = {
            "areas": {"room1": {}, "room2": {}},
            "adjacency": {"room1": ["room2"]},
            "sensors": {
                "sensor.motion_1": {"area": "room1", "type": "motion"},
            },
        }

        coordinator = OccupancyCoordinator(hass, config)
        timestamp = time.time()

        # Set up some state
        coordinator.areas["room1"].occupancy = 2
        coordinator.areas["room1"].record_motion(timestamp)
        coordinator.process_sensor_event("sensor.motion_1", True, timestamp)

        # Reset
        coordinator.reset()

        # Everything should be cleared
        assert coordinator.areas["room1"].occupancy == 0
        assert coordinator.areas["room1"].last_motion == 0
        assert coordinator.sensors["sensor.motion_1"].current_state is False
        assert len(coordinator.get_warnings()) == 0

    def test_reset_anomalies(self):
        """Test resetting only anomalies (not occupancy state)."""
        hass = Mock(spec=HomeAssistant)
        config = {
            "areas": {"room1": {}},
            "adjacency": {},
            "sensors": {},
        }

        coordinator = OccupancyCoordinator(hass, config)

        # Set up state and warnings
        coordinator.areas["room1"].occupancy = 1
        coordinator.anomaly_detector._create_warning("test", "Test")

        # Reset anomalies only
        coordinator.reset_anomalies()

        # Occupancy preserved, warnings cleared
        assert coordinator.areas["room1"].occupancy == 1
        assert len(coordinator.get_warnings()) == 0

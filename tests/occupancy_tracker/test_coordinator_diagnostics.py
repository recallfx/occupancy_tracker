"""Tests for coordinator diagnostics functionality."""

import time
from unittest.mock import Mock

from homeassistant.core import HomeAssistant
from custom_components.occupancy_tracker.coordinator import OccupancyCoordinator


class TestOccupancyCoordinatorDiagnostics:
    """Test diagnostic methods."""

    def test_diagnose_motion_issues_single_sensor(self):
        """Test diagnosing issues with a specific sensor."""
        hass = Mock(spec=HomeAssistant)
        config = {
            "areas": {"living_room": {}},
            "adjacency": {},
            "sensors": {
                "sensor.motion_living": {"area": "living_room", "type": "motion"},
            },
        }

        coordinator = OccupancyCoordinator(hass, config)

        result = coordinator.diagnose_motion_issues("sensor.motion_living")

        assert "sensor.motion_living" in result
        assert result["sensor.motion_living"]["is_motion_sensor"] is True
        assert result["sensor.motion_living"]["sensor_type"] == "motion"
        assert result["sensor.motion_living"]["area_exists"] is True

    def test_diagnose_motion_issues_all_sensors(self):
        """Test diagnosing all sensors."""
        hass = Mock(spec=HomeAssistant)
        config = {
            "areas": {"room1": {}, "room2": {}},
            "adjacency": {},
            "sensors": {
                "sensor.motion_1": {"area": "room1", "type": "motion"},
                "sensor.motion_2": {"area": "room2", "type": "camera_motion"},
            },
        }

        coordinator = OccupancyCoordinator(hass, config)

        result = coordinator.diagnose_motion_issues()

        assert len(result) == 2
        assert "sensor.motion_1" in result
        assert "sensor.motion_2" in result

    def test_diagnose_motion_issues_unknown_sensor(self):
        """Test diagnosing unknown sensor."""
        hass = Mock(spec=HomeAssistant)
        config = {"areas": {}, "adjacency": {}, "sensors": {}}

        coordinator = OccupancyCoordinator(hass, config)

        result = coordinator.diagnose_motion_issues("sensor.unknown")

        assert "sensor.unknown" in result
        assert "error" in result["sensor.unknown"]

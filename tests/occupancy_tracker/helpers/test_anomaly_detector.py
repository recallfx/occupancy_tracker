"""Tests for AnomalyDetector."""

import time

from custom_components.occupancy_tracker.helpers.anomaly_detector import (
    AnomalyDetector,
)
from custom_components.occupancy_tracker.helpers.area_state import AreaState
from custom_components.occupancy_tracker.helpers.sensor_state import SensorState


class TestAnomalyDetector:
    """Test AnomalyDetector class."""

    def test_create_detector(self):
        """Test creating an anomaly detector."""
        config = {
            "areas": {},
            "adjacency": {},
            "sensors": {},
        }
        detector = AnomalyDetector(config)

        assert detector.config == config
        assert detector.warnings == []
        assert detector.recent_motion_window == 120
        assert detector.motion_timeout == 24 * 3600
        assert detector.extended_occupancy_threshold == 12 * 3600

    def test_create_warning(self):
        """Test creating a warning."""
        config = {"areas": {}, "adjacency": {}, "sensors": {}}
        detector = AnomalyDetector(config)
        timestamp = time.time()

        warning = detector._create_warning(
            warning_type="test_warning",
            message="Test message",
            area="living_room",
            sensor_id="sensor.motion_1",
            timestamp=timestamp,
        )

        assert warning.type == "test_warning"
        assert warning.message == "Test message"
        assert warning.area == "living_room"
        assert warning.sensor_id == "sensor.motion_1"
        assert warning.timestamp == timestamp
        assert len(detector.warnings) == 1

    def test_get_warnings_active_only(self):
        """Test getting only active warnings."""
        config = {"areas": {}, "adjacency": {}, "sensors": {}}
        detector = AnomalyDetector(config)

        # Create some warnings
        detector._create_warning("type1", "Message 1")
        w2 = detector._create_warning("type2", "Message 2")
        detector._create_warning("type3", "Message 3")

        # Resolve one
        w2.resolve()

        active_warnings = detector.get_warnings(active_only=True)

        assert len(active_warnings) == 2
        assert w2 not in active_warnings

    def test_get_warnings_all(self):
        """Test getting all warnings including resolved."""
        config = {"areas": {}, "adjacency": {}, "sensors": {}}
        detector = AnomalyDetector(config)

        w1 = detector._create_warning("type1", "Message 1")
        detector._create_warning("type2", "Message 2")

        w1.resolve()

        all_warnings = detector.get_warnings(active_only=False)

        assert len(all_warnings) == 2

    def test_resolve_warning(self):
        """Test resolving a warning by ID."""
        config = {"areas": {}, "adjacency": {}, "sensors": {}}
        detector = AnomalyDetector(config)

        warning = detector._create_warning("stuck_sensor", "Sensor stuck")

        result = detector.resolve_warning(warning.id)

        assert result is True
        assert warning.is_active is False

    def test_resolve_nonexistent_warning(self):
        """Test resolving a warning that doesn't exist."""
        config = {"areas": {}, "adjacency": {}, "sensors": {}}
        detector = AnomalyDetector(config)

        result = detector.resolve_warning("nonexistent_id")

        assert result is False

    def test_check_for_stuck_sensors(self):
        """Test checking for stuck sensors."""
        config = {
            "areas": {
                "living_room": {"name": "Living Room"},
                "kitchen": {"name": "Kitchen"},
            },
            "adjacency": {"living_room": ["kitchen"]},
            "sensors": {},
        }
        detector = AnomalyDetector(config)

        timestamp = time.time()

        # Create sensors - one with very old last update
        sensors = {
            "sensor.motion_living": SensorState(
                "sensor.motion_living",
                {"area": "living_room", "type": "motion"},
                timestamp,
            ),
            "sensor.motion_kitchen": SensorState(
                "sensor.motion_kitchen",
                {"area": "kitchen", "type": "motion"},
                timestamp - 100000,  # Very old - over 24 hours ago
            ),
        }

        # Update kitchen sensor to "on" state so it can be detected as stuck
        sensors["sensor.motion_kitchen"].update_state(True, timestamp - 100000)

        areas = {
            "living_room": AreaState("living_room", {"name": "Living Room"}),
            "kitchen": AreaState("kitchen", {"name": "Kitchen"}),
        }

        detector.check_for_stuck_sensors(sensors, areas, "sensor.motion_living")

        # Should create a warning for the stuck sensor
        warnings = detector.get_warnings()
        assert len(warnings) == 1
        assert warnings[0].type == "stuck_sensor"
        assert warnings[0].sensor_id == "sensor.motion_kitchen"
        assert warnings[0].type == "stuck_sensor"
        assert "sensor.motion_kitchen" in warnings[0].message

    def test_check_timeouts_inactivity_reset(self):
        """Test that areas are reset after 24 hours of inactivity."""
        config = {"areas": {}, "adjacency": {}, "sensors": {}}
        detector = AnomalyDetector(config)

        timestamp = time.time()

        areas = {
            "bedroom": AreaState("bedroom", {"name": "Bedroom"}),
        }

        # Set up occupied area with old motion
        areas["bedroom"].occupancy = 2
        areas["bedroom"].last_motion = timestamp - (25 * 3600)  # 25 hours ago

        detector.check_timeouts(areas, timestamp)

        # Should reset occupancy
        assert areas["bedroom"].occupancy == 0

        # Should create warning
        warnings = detector.get_warnings()
        assert len(warnings) == 1
        assert warnings[0].type == "inactivity_timeout"

    def test_check_timeouts_extended_occupancy(self):
        """Test warning for extended occupancy (12+ hours)."""
        config = {"areas": {}, "adjacency": {}, "sensors": {}}
        detector = AnomalyDetector(config)

        timestamp = time.time()

        areas = {
            "office": AreaState("office", {"name": "Office"}),
        }

        # Set up occupied area with 13 hours of inactivity
        areas["office"].occupancy = 1
        areas["office"].last_motion = timestamp - (13 * 3600)

        detector.check_timeouts(areas, timestamp)

        # Should not reset (under 24 hours) but should warn
        assert areas["office"].occupancy == 1

        # Should create warning
        warnings = detector.get_warnings()
        assert len(warnings) == 1
        assert warnings[0].type == "extended_occupancy"

    def test_check_timeouts_no_duplicate_extended_occupancy_warning(self):
        """Test that extended occupancy warning is not duplicated."""
        config = {"areas": {}, "adjacency": {}, "sensors": {}}
        detector = AnomalyDetector(config)

        timestamp = time.time()

        areas = {
            "office": AreaState("office", {"name": "Office"}),
        }

        # Set up occupied area with 13 hours of inactivity
        areas["office"].occupancy = 1
        areas["office"].last_motion = timestamp - (13 * 3600)

        # Check timeouts twice
        detector.check_timeouts(areas, timestamp)
        detector.check_timeouts(areas, timestamp + 100)

        # Should only have one warning
        warnings = detector.get_warnings()
        assert len(warnings) == 1

    def test_check_timeouts_recent_activity_no_warning(self):
        """Test that recent activity doesn't trigger warnings."""
        config = {"areas": {}, "adjacency": {}, "sensors": {}}
        detector = AnomalyDetector(config)

        timestamp = time.time()

        areas = {
            "kitchen": AreaState("kitchen", {"name": "Kitchen"}),
        }

        # Occupied with recent motion
        areas["kitchen"].occupancy = 1
        areas["kitchen"].record_motion(timestamp - 60)  # 1 minute ago

        detector.check_timeouts(areas, timestamp)

        # Should not create any warnings
        warnings = detector.get_warnings()
        assert len(warnings) == 0

    def test_multiple_warning_types(self):
        """Test that different warning types can coexist."""
        config = {
            "areas": {"room1": {}, "room2": {}},
            "adjacency": {},
            "sensors": {},
        }
        detector = AnomalyDetector(config)

        # Create different types of warnings
        detector._create_warning("stuck_sensor", "Sensor stuck", sensor_id="sensor.1")
        detector._create_warning("unexpected_motion", "Unexpected", area="room1")
        detector._create_warning("inactivity_timeout", "Timeout", area="room2")

        warnings = detector.get_warnings()

        assert len(warnings) == 3
        warning_types = {w.type for w in warnings}
        assert warning_types == {
            "stuck_sensor",
            "unexpected_motion",
            "inactivity_timeout",
        }

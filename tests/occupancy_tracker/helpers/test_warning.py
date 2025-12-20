"""Tests for Warning."""

import time
from custom_components.occupancy_tracker.helpers.warning import Warning


class TestWarning:
    """Test Warning class."""

    def test_create_warning(self):
        """Test creating a basic warning."""
        timestamp = time.time()
        warning = Warning(
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
        assert warning.is_active is True
        assert "test_warning" in warning.id
        assert "living_room" in warning.id
        assert "sensor.motion_1" in warning.id

    def test_warning_without_area_or_sensor(self):
        """Test creating a warning without area or sensor."""
        timestamp = time.time()
        warning = Warning(
            warning_type="general_warning",
            message="General message",
            area=None,
            sensor_id=None,
            timestamp=timestamp,
        )

        assert warning.area is None
        assert warning.sensor_id is None
        assert warning.is_active is True

    def test_resolve_warning(self):
        """Test resolving a warning."""
        warning = Warning(
            warning_type="test",
            message="Test",
            area=None,
            sensor_id=None,
            timestamp=time.time(),
        )

        assert warning.is_active is True
        warning.resolve()
        assert warning.is_active is False

    def test_warning_string_representation(self):
        """Test warning string representation."""
        warning = Warning(
            warning_type="stuck_sensor",
            message="Sensor appears stuck",
            area="bedroom",
            sensor_id="sensor.motion_2",
            timestamp=time.time(),
        )

        str_repr = str(warning)
        assert "Warning[stuck_sensor]" in str_repr
        assert "Sensor appears stuck" in str_repr

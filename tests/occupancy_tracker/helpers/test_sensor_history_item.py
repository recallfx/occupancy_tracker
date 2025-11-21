"""Tests for SensorHistoryItem."""

import time
from custom_components.occupancy_tracker.helpers.sensor_history_item import (
    SensorHistoryItem,
)


class TestSensorHistoryItem:
    """Test SensorHistoryItem class."""

    def test_create_history_item(self):
        """Test creating a sensor history item."""
        timestamp = time.time()
        item = SensorHistoryItem(state=True, timestamp=timestamp)

        assert item.state is True
        assert item.timestamp == timestamp

    def test_create_false_state(self):
        """Test creating a history item with False state."""
        timestamp = time.time()
        item = SensorHistoryItem(state=False, timestamp=timestamp)

        assert item.state is False
        assert item.timestamp == timestamp

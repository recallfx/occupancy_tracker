"""Tests for AreaState."""

import time
from custom_components.occupancy_tracker.helpers.area_state import AreaState


class TestAreaState:
    """Test AreaState class."""

    def test_create_area_state(self):
        """Test creating an area state."""
        config = {
            "name": "Living Room",
            "indoors": True,
            "exit_capable": False,
        }
        area = AreaState("living_room", config)

        assert area.id == "living_room"
        assert area.config == config
        assert area.occupancy == 0
        assert area.last_motion == 0
        assert area.activity_history == []
        assert area.is_indoors is True
        assert area.is_exit_capable is False

    def test_area_defaults(self):
        """Test area state with default values."""
        area = AreaState("bedroom", {})

        assert area.is_indoors is True  # Default
        assert area.is_exit_capable is False  # Default

    def test_outdoor_exit_capable_area(self):
        """Test outdoor exit-capable area."""
        config = {"indoors": False, "exit_capable": True}
        area = AreaState("front_porch", config)

        assert area.is_indoors is False
        assert area.is_exit_capable is True

    def test_record_motion(self):
        """Test recording motion in an area."""
        area = AreaState("kitchen", {})
        timestamp = time.time()

        area.record_motion(timestamp)

        assert area.last_motion == timestamp
        assert len(area.activity_history) == 1
        assert area.activity_history[0] == (timestamp, "motion")

    def test_record_multiple_motions(self):
        """Test recording multiple motion events."""
        area = AreaState("kitchen", {})
        timestamp1 = time.time()
        timestamp2 = timestamp1 + 10

        area.record_motion(timestamp1)
        area.record_motion(timestamp2)

        assert area.last_motion == timestamp2
        assert len(area.activity_history) == 2

    def test_record_entry(self):
        """Test recording entry into an area."""
        area = AreaState("bathroom", {})
        timestamp = time.time()

        area.record_entry(timestamp)

        assert area.occupancy == 1
        assert len(area.activity_history) == 1
        assert area.activity_history[0] == (timestamp, "entry")

    def test_record_entry_with_claim(self):
        """Test recording entry with an explicit claim."""
        area = AreaState("bathroom", {})
        timestamp = time.time()

        area.record_entry(timestamp, claim_id="c0")

        assert area.occupancy == 1
        assert area.is_occupied is True

    def test_multiple_entries(self):
        """Test multiple entries keep area occupied (binary occupancy)."""
        area = AreaState("office", {})
        timestamp = time.time()

        area.record_entry(timestamp, claim_id="c0")
        area.record_entry(timestamp + 5, claim_id="c1")

        # In the clustering model, occupancy is binary (0 or 1)
        assert area.occupancy == 1
        assert area.is_occupied is True

    def test_record_exit(self):
        """Test recording exit from an area."""
        area = AreaState("garage", {})
        timestamp = time.time()

        area.record_entry(timestamp)
        result = area.record_exit(timestamp + 10)

        assert result is True
        assert area.occupancy == 0
        assert len(area.activity_history) == 2

    def test_exit_without_occupancy(self):
        """Test exit when area is unoccupied."""
        area = AreaState("hallway", {})
        timestamp = time.time()

        result = area.record_exit(timestamp)

        assert result is False
        assert area.occupancy == 0

    def test_occupancy_setter_zero_clears(self):
        """Test that setting occupancy to 0 clears occupancy."""
        area = AreaState("test", {})
        area.claims.add("c0")
        assert area.occupancy == 1

        area.occupancy = 0
        assert area.occupancy == 0
        assert len(area.claims) == 0

    def test_get_inactivity_duration(self):
        """Test calculating inactivity duration."""
        area = AreaState("bedroom", {})
        start_time = time.time()

        area.record_motion(start_time)

        # Check inactivity after 60 seconds
        current_time = start_time + 60
        duration = area.get_inactivity_duration(current_time)

        assert duration == 60

    def test_has_recent_motion_true(self):
        """Test has_recent_motion returns True when motion is recent."""
        area = AreaState("kitchen", {})
        timestamp = time.time()

        area.record_motion(timestamp)

        # Check 30 seconds later
        assert area.has_recent_motion(timestamp + 30, within_seconds=120) is True

    def test_has_recent_motion_false(self):
        """Test has_recent_motion returns False when motion is old."""
        area = AreaState("kitchen", {})
        timestamp = time.time()

        area.record_motion(timestamp)

        # Check 150 seconds later (outside default 120 second window)
        assert area.has_recent_motion(timestamp + 150, within_seconds=120) is False

    def test_has_recent_motion_no_motion(self):
        """Test has_recent_motion when no motion recorded."""
        area = AreaState("basement", {})
        timestamp = time.time()

        assert area.has_recent_motion(timestamp) is False

    def test_activity_history_max_length(self):
        """Test that activity history maintains max length."""
        from custom_components.occupancy_tracker.helpers.constants import (
            MAX_HISTORY_LENGTH,
        )

        area = AreaState("test_area", {})
        timestamp = time.time()

        # Record more events than max length
        for i in range(MAX_HISTORY_LENGTH + 50):
            area.record_motion(timestamp + i)

        assert len(area.activity_history) == MAX_HISTORY_LENGTH

    def test_is_occupied_property(self):
        """Test is_occupied computed property."""
        area = AreaState("test", {})
        assert area.is_occupied is False

        area.occupied = True
        assert area.is_occupied is True

        area.occupied = False
        assert area.is_occupied is False

    def test_clear_occupancy(self):
        """Test clear_occupancy clears occupancy."""
        area = AreaState("test", {})
        area.occupied = True
        assert area.occupancy == 1

        area.clear_occupancy(100.0)
        assert area.occupancy == 0
        assert len(area.claims) == 0

    def test_reset(self):
        """Test reset clears all state."""
        area = AreaState("test", {})
        area.occupied = True
        area.last_motion = 100.0
        area.activity_history = [(100.0, "motion")]

        area.reset()
        assert area.occupancy == 0
        assert area.last_motion == 0
        assert area.activity_history == []

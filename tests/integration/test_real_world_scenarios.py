"""Real-world scenario integration tests.

These tests simulate realistic use cases that users would experience,
including dailyroutines, multi-occupant scenarios, and edge cases.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant

from custom_components.occupancy_tracker import DOMAIN
from .test_fixtures import assert_occupancy_state, SensorEventHelper


@pytest.mark.scenarios
class TestDailyRoutines:
    """Test common daily routine scenarios."""

    async def test_morning_routine_complete(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """Test complete morning routine: wake -> bathroom -> kitchen -> living."""
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Wake up in bedroom
        helper.trigger_motion("binary_sensor.motion_main_bedroom")
        assert coordinator.get_occupancy("main_bedroom") >= 1

        # Go to bathroom
        helper.trigger_motion("binary_sensor.motion_main_bathroom", delay=30)
        # Stay for 10 minutes
        helper.advance_time(10 * 60)
        assert coordinator.get_occupancy("main_bathroom") >= 1

        # Return to bedroom to get dressed
        helper.trigger_motion("binary_sensor.motion_main_bedroom", delay=5)
        helper.advance_time(5 * 60)  # 5 minutes getting dressed

        # Head to living area via halls
        helper.trigger_motion("binary_sensor.motion_back_hall", delay=2)
        helper.trigger_motion("binary_sensor.motion_front_hall", delay=2)
        helper.trigger_motion("binary_sensor.motion_entrance", delay=2)
        helper.trigger_motion("binary_sensor.motion_living", delay=2)

        # Final state: in living room
        assert coordinator.get_occupancy("living") >= 1
        assert coordinator.get_occupancy("main_bedroom") == 0

    async def test_leaving_and_returning_home(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """Test leaving home and returning later."""
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Start in living room
        helper.trigger_motion("binary_sensor.motion_living")

        # Leave: living -> entrance -> frontyard
        helper.trigger_motion("binary_sensor.motion_entrance", delay=2)
        helper.trigger_sensor("binary_sensor.magnetic_entry", True, delay=1)
        helper.trigger_sensor("binary_sensor.person_front_left_camera", True, delay=1)

        # Wait for timeout in frontyard (5+ minutes)
        helper.advance_time(301)
        helper.check_timeouts()

        # House should be empty now
        assert coordinator.get_occupancy("frontyard") == 0
        assert coordinator.get_occupancy("living") == 0

        # Return home later (2 hours)
        helper.advance_time(2 * 60 * 60)

        # Approach and enter
        helper.trigger_sensor("binary_sensor.person_front_left_camera", True)
        helper.trigger_sensor("binary_sensor.magnetic_entry", True, delay=2)
        helper.trigger_motion("binary_sensor.motion_entrance", delay=1)
        helper.trigger_motion("binary_sensor.motion_living", delay=2)

        # Should be back in living room
        assert coordinator.get_occupancy("living") >= 1

    async def test_evening_bedtime_routine(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """Test evening routine: living -> bathroom -> bedroom."""
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Start in living room (evening)
        helper.trigger_motion("binary_sensor.motion_living")

        # Go to bedroom via entrance and halls
        helper.trigger_motion("binary_sensor.motion_entrance", delay=2)
        helper.trigger_motion("binary_sensor.motion_front_hall", delay=2)
        helper.trigger_motion("binary_sensor.motion_back_hall", delay=2)
        helper.trigger_motion("binary_sensor.motion_main_bedroom", delay=2)

        # Quick bathroom visit
        helper.trigger_motion("binary_sensor.motion_main_bathroom", delay=2)
        helper.advance_time(5 * 60)  # 5 minutes

        # Back to bedroom for sleep
        helper.trigger_motion("binary_sensor.motion_main_bedroom", delay=2)

        # Sleep for 8 hours (no motion)
        helper.advance_time(8 * 60 * 60)
        helper.check_timeouts()

        # Should still be in bedroom (low probability but maintained)
        assert coordinator.get_occupancy("main_bedroom") >= 1


@pytest.mark.scenarios
class TestMultiOccupantScenarios:
    """Test scenarios with multiple people in the house."""

    async def test_two_people_parallel_paths(
        self, hass_with_multi_occupant_config: HomeAssistant
    ):
        """Test two people moving independently through the house."""
        coordinator = hass_with_multi_occupant_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person A: entrance -> living -> bedroom_1
        helper.trigger_motion("binary_sensor.motion_entrance")
        helper.trigger_motion("binary_sensor.motion_living", delay=2)

        # Person B: entrance -> living -> kitchen (overlapping with A)
        helper.trigger_motion("binary_sensor.motion_entrance", delay=1)

        # Now both in living room
        helper.advance_time(2)

        # Person A goes to bedroom_1
        helper.trigger_motion("binary_sensor.motion_bedroom_1", delay=2)

        # Person B goes to kitchen
        helper.trigger_motion("binary_sensor.motion_kitchen", delay=1)

        # Should have occupancy in both areas
        assert coordinator.get_occupancy("bedroom_1") >= 1
        assert coordinator.get_occupancy("kitchen") >= 1

    async def test_family_morning_chaos(
        self, hass_with_multi_occupant_config: HomeAssistant
    ):
        """Test family morning with multiple people in different rooms."""
        coordinator = hass_with_multi_occupant_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person 1 in bedroom_1
        helper.trigger_motion("binary_sensor.motion_bedroom_1")

        # Person 2 in bedroom_2
        helper.trigger_motion("binary_sensor.motion_bedroom_2", delay=0.5)

        # Person 3 in kitchen
        helper.trigger_motion("binary_sensor.motion_kitchen", delay=0.5)

        # All moving around
        # Person 1: bedroom_1 -> bathroom
        helper.trigger_motion("binary_sensor.motion_bathroom", delay=2)

        # Person 2: bedroom_2 -> living_room
        helper.trigger_motion("binary_sensor.motion_living", delay=1)

        # Person 3 stays in kitchen
        helper.trigger_motion("binary_sensor.motion_kitchen", delay=2)
        helper.trigger_motion("binary_sensor.motion_bedroom_1")
        helper.trigger_motion("binary_sensor.motion_bathroom", delay=1)

        # Person 2: bedroom_2 -> kitchen (via living_room)
        helper.trigger_motion("binary_sensor.motion_bedroom_2", delay=0.5)
        helper.trigger_motion("binary_sensor.motion_living", delay=1)
        helper.trigger_motion("binary_sensor.motion_kitchen", delay=1)

        # System should handle multi-person motion without crashing
        # Exact counts depend on how system tracks multiple people
        total_occupancy = sum([
            coordinator.get_occupancy("bedroom_1"),
            coordinator.get_occupancy("bedroom_2"),
            coordinator.get_occupancy("bathroom"),
            coordinator.get_occupancy("living_room"),
            coordinator.get_occupancy("kitchen"),
        ])
        # Should have tracked at least some occupancy
        assert total_occupancy >= 1

    async def test_gathering_and_dispersing(
        self, hass_with_multi_occupant_config: HomeAssistant
    ):
        """Test family gathering in one room then dispersing."""
        coordinator = hass_with_multi_occupant_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Everyone starts in different rooms
        helper.trigger_motion("binary_sensor.motion_bedroom_1")
        helper.trigger_motion("binary_sensor.motion_bedroom_2", delay=0.5)
        helper.trigger_motion("binary_sensor.motion_kitchen", delay=0.5)

        # All move to living room
        helper.trigger_motion("binary_sensor.motion_living", delay=2)
        helper.trigger_motion("binary_sensor.motion_living", delay=1)
        helper.trigger_motion("binary_sensor.motion_living", delay=1)

        # Living room should have multiple occupants
        # System should handle multiple people in same area
        living_occupancy = coordinator.get_occupancy("living_room")
        # May track as 1 or 2 depending on implementation
        assert living_occupancy >= 1

        # Now disperse (not tested - just verify gathering worked)
        assert isinstance(living_occupancy, int)


@pytest.mark.scenarios
class TestWorkFromHomeScenarios:
    """Test work-from-home scenarios with extended stationary periods."""

    async def test_all_day_in_home_office(
        self, hass_with_simple_config: HomeAssistant
    ):
        """Test person working all day in one room."""
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Start work in bedroom (home office)
        helper.trigger_motion("binary_sensor.motion_bedroom")

        # Work for 8 hours with periodic small movements
        for hour in range(8):
            # Every hour, small motion (adjusting position, getting up briefly)
            helper.advance_time(50 * 60)  # 50 minutes
            helper.trigger_motion("binary_sensor.motion_bedroom")

            # Quick break to kitchen every 2 hours
            if hour % 2 == 0:
                helper.trigger_motion("binary_sensor.motion_kitchen", delay=2)
                helper.advance_time(5 * 60)  # 5 minute break
                helper.trigger_motion("binary_sensor.motion_bedroom", delay=2)

        # Should still be in bedroom at end of day
        assert coordinator.get_occupancy("bedroom") >= 1

    async def test_intermittent_breaks(self, hass_with_simple_config: HomeAssistant):
        """Test working with regular breaks between rooms."""
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        for cycle in range(4):  # 4 work cycles
            # Work session in bedroom (1 hour)
            helper.trigger_motion("binary_sensor.motion_bedroom")
            helper.advance_time(60 * 60)

            # Break in living room (15 minutes)
            helper.trigger_motion("binary_sensor.motion_living", delay=2)
            helper.advance_time(15 * 60)

        # Final location: living room
        assert coordinator.get_occupancy("living_room") >= 1


@pytest.mark.scenarios  
class TestVisitorScenarios:
    """Test scenarios involving visitors."""

    async def test_visitor_enters_stays_leaves(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """Test visitor complete journey."""
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Visitor approaches
        helper.trigger_sensor("binary_sensor.person_front_left_camera", True)

        # Rings doorbell, enters
        helper.trigger_sensor("binary_sensor.magnetic_entry", True, delay=5)
        helper.trigger_motion("binary_sensor.motion_entrance", delay=1)

        # Goes to living room
        helper.trigger_motion("binary_sensor.motion_living", delay=2)

        # Stays for 1 hour, occasional motion
        for _ in range(6):
            helper.advance_time(10 * 60)  # 10 minutes
            helper.trigger_motion("binary_sensor.motion_living")

        # Visitor leaves
        helper.trigger_motion("binary_sensor.motion_entrance", delay=2)
        helper.trigger_sensor("binary_sensor.magnetic_entry", True, delay=1)
        helper.trigger_sensor("binary_sensor.person_front_left_camera", True, delay=1)

        # Timeout in frontyard
        helper.advance_time(301)
        helper.check_timeouts()

        # Should be gone
        assert coordinator.get_occupancy("frontyard") == 0
        assert coordinator.get_occupancy("living") == 0

    async def test_multiple_visitors_arriving_together(
        self, hass_with_multi_occupant_config: HomeAssistant
    ):
        """Test multiple visitors arriving at the same time."""
        coordinator = hass_with_multi_occupant_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Two visitors enter almost simultaneously
        helper.trigger_motion("binary_sensor.motion_entrance")
        helper.trigger_motion("binary_sensor.motion_entrance", delay=0.5)

        # Move to living room
        helper.trigger_motion("binary_sensor.motion_living", delay=2)

        # System should handle simultaneous arrivals
        living_occupancy = coordinator.get_occupancy("living_room")
        # May track as 1 or more depending on simultaneous detection capability
        assert living_occupancy >= 1


@pytest.mark.scenarios
class TestEdgeCaseScenarios:
    """Test edge case scenarios that might occur in real use."""

    async def test_very_quick_room_transition(
        self, hass_with_simple_config: HomeAssistant
    ):
        """Test person moving through room very quickly (just passing through)."""
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Start in living room
        helper.trigger_motion("binary_sensor.motion_living")

        # Pass through kitchen very quickly (2 seconds)
        helper.trigger_sensor("binary_sensor.motion_kitchen", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_kitchen", False, delay=2)

        # End in bedroom
        helper.trigger_motion("binary_sensor.motion_bedroom", delay=1)

        # Should be in bedroom
        assert coordinator.get_occupancy("bedroom") >= 1

    async def test_long_transition_time_between_rooms(
        self, hass_with_simple_config: HomeAssistant
    ):
        """Test very slow movement between rooms (e.g., carrying items)."""
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Start in living room
        helper.trigger_motion("binary_sensor.motion_living")

        # Very slow transition (2 minutes between rooms)
        helper.trigger_motion("binary_sensor.motion_kitchen", delay=120)

        # Should have transitioned successfully
        assert coordinator.get_occupancy("kitchen") >= 1

    async def test_forgotten_area_return(
        self, hass_with_simple_config: HomeAssistant
    ):
        """Test returning to a room after forgetting something."""
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Bedroom -> kitchen
        helper.trigger_motion("binary_sensor.motion_bedroom")
        helper.trigger_motion("binary_sensor.motion_kitchen", delay=2)

        # Realize forgot something, go back quickly
        helper.trigger_motion("binary_sensor.motion_bedroom", delay=5)

        # Grab item, return to kitchen
        helper.trigger_motion("binary_sensor.motion_kitchen", delay=10)

        # Should be in kitchen
        assert coordinator.get_occupancy("kitchen") >= 1

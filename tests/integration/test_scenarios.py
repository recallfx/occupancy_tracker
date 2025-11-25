"""
Real-world scenario integration tests.

Notation:
- Areas: Y=Frontyard, E=Entrance, F=Front Hall, B=Back Hall, M=Main Bedroom, 
         Mb=Main Bathroom, L=Living, Bk=Backyard
- Motion: + = active
- Occupancy: @ = occupied
- Door: | = closed, / = open

Tests organized by scenario type:
- Single person journeys
- Multi-occupant scenarios  
- Work from home patterns
- Visitor scenarios
- Timeout/probability behavior
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant

from custom_components.occupancy_tracker import DOMAIN
from .test_fixtures import assert_occupancy_state, SensorEventHelper


# =============================================================================
# Single Person Journey Tests
# =============================================================================

@pytest.mark.scenarios
class TestSinglePersonJourneys:
    """Test complete single person journeys through the house."""

    async def test_morning_routine(self, hass_with_realistic_config: HomeAssistant):
        """
        Morning routine: wake -> bathroom -> bedroom -> halls -> living.
        
        M+@ -> Mb+@ -> M+@ -> B+@ -> F+@ -> E+@ -> L+@
        """
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # M+@ - wake up
        helper.trigger_motion("binary_sensor.motion_main_bedroom")
        assert coordinator.get_occupancy("main_bedroom") >= 1

        # Mb+@ - bathroom (10 min stay)
        helper.trigger_motion("binary_sensor.motion_main_bathroom", delay=30)
        helper.advance_time(10 * 60)
        assert coordinator.get_occupancy("main_bathroom") >= 1

        # M+@ - back to bedroom (5 min getting dressed)
        helper.trigger_motion("binary_sensor.motion_main_bedroom", delay=5)
        helper.advance_time(5 * 60)

        # B+@ -> F+@ -> E+@ -> L+@ - head to living
        helper.trigger_motion("binary_sensor.motion_back_hall", delay=2)
        helper.trigger_motion("binary_sensor.motion_front_hall", delay=2)
        helper.trigger_motion("binary_sensor.motion_entrance", delay=2)
        helper.trigger_motion("binary_sensor.motion_living", delay=2)

        # Final: in living room
        assert coordinator.get_occupancy("living") >= 1
        assert coordinator.get_occupancy("main_bedroom") == 0

    async def test_leave_and_return(self, hass_with_realistic_config: HomeAssistant):
        """
        Leave home via frontyard, return 2 hours later.
        
        L+@ -> E+@ -> Y+@/ -> (timeout) -> Y@=0
        ...2 hours...
        Y+@ -> /E+@ -> L+@
        """
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Start in living
        helper.trigger_motion("binary_sensor.motion_living")

        # Exit sequence: L -> E -> Y
        helper.trigger_motion("binary_sensor.motion_entrance", delay=2)
        helper.trigger_sensor("binary_sensor.magnetic_entry", True, delay=1)
        helper.trigger_sensor("binary_sensor.person_front_left_camera", True, delay=1)

        # Wait for exit-capable timeout
        helper.advance_time(301)
        helper.check_timeouts()

        # House empty
        assert coordinator.get_occupancy("frontyard") == 0
        assert coordinator.get_occupancy("living") == 0

        # Return 2 hours later
        helper.advance_time(2 * 60 * 60)
        helper.trigger_sensor("binary_sensor.person_front_left_camera", True)
        helper.trigger_sensor("binary_sensor.magnetic_entry", True, delay=2)
        helper.trigger_motion("binary_sensor.motion_entrance", delay=1)
        helper.trigger_motion("binary_sensor.motion_living", delay=2)

        assert coordinator.get_occupancy("living") >= 1

    async def test_enter_and_exit_same_door(self, hass_with_realistic_config: HomeAssistant):
        """
        Enter, go to back hall, then exit.
        
        Entry: Y+@/EFB -> ... -> Y/EFB+@
        Exit:  Y/EFB+@ -> Y/EF+@B -> Y/E+@FB -> Y+@/EFB
        """
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Entry sequence
        helper.trigger_sensor("binary_sensor.person_front_left_camera", True)
        helper.trigger_sensor("binary_sensor.magnetic_entry", True, delay=0.5)
        helper.trigger_sensor("binary_sensor.magnetic_entry", False, delay=0.5)
        helper.trigger_sensor("binary_sensor.motion_entrance", True, delay=0.5)
        helper.trigger_sensor("binary_sensor.person_front_left_camera", False, delay=0.5)
        helper.trigger_sensor("binary_sensor.motion_front_hall", True, delay=0.5)
        helper.trigger_sensor("binary_sensor.motion_back_hall", True, delay=0.5)

        assert coordinator.get_occupancy("back_hall") == 1

        # Clear sensors
        helper.trigger_sensor("binary_sensor.motion_entrance", False, delay=2)
        helper.trigger_sensor("binary_sensor.motion_front_hall", False, delay=0.5)

        # Exit sequence: B -> F -> E -> Y
        helper.trigger_sensor("binary_sensor.motion_front_hall", True, delay=3)
        assert coordinator.get_occupancy("front_hall") == 1
        assert coordinator.get_occupancy("back_hall") == 0

        helper.trigger_sensor("binary_sensor.motion_entrance", True, delay=0.5)
        assert coordinator.get_occupancy("entrance") == 1

        helper.trigger_sensor("binary_sensor.person_front_left_camera", True, delay=0.5)
        assert coordinator.get_occupancy("frontyard") == 1
        assert coordinator.get_occupancy("entrance") == 0


# =============================================================================
# Multi-Occupant Tests
# =============================================================================

@pytest.mark.scenarios
class TestMultiOccupant:
    """Test scenarios with multiple people."""

    async def test_two_people_different_destinations(
        self, hass_with_multi_occupant_config: HomeAssistant
    ):
        """
        P1 goes to bedroom_1, P2 goes to kitchen.
        
        E+@ -> L+@ -> (P1) B1+@, (P2) K+@
        Final: B1@=1, K@=1
        """
        coordinator = hass_with_multi_occupant_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Both start from entrance -> living
        helper.trigger_motion("binary_sensor.motion_entrance")
        helper.trigger_motion("binary_sensor.motion_living", delay=2)

        # P2 enters via entrance (second person)
        helper.trigger_motion("binary_sensor.motion_entrance", delay=1)
        helper.advance_time(2)

        # P1 -> bedroom_1
        helper.trigger_motion("binary_sensor.motion_bedroom_1", delay=2)

        # P2 -> kitchen
        helper.trigger_motion("binary_sensor.motion_kitchen", delay=1)

        assert coordinator.get_occupancy("bedroom_1") >= 1
        assert coordinator.get_occupancy("kitchen") >= 1

    async def test_family_dispersed(self, hass_with_multi_occupant_config: HomeAssistant):
        """
        Three people in different rooms simultaneously.
        
        B1+@ B2+@ K+@ (all independent)
        """
        coordinator = hass_with_multi_occupant_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # All three trigger almost simultaneously
        helper.trigger_motion("binary_sensor.motion_bedroom_1")
        helper.trigger_motion("binary_sensor.motion_bedroom_2", delay=0.5)
        helper.trigger_motion("binary_sensor.motion_kitchen", delay=0.5)

        # Should handle without crashing; at least 1 occupancy somewhere
        total = sum([
            coordinator.get_occupancy("bedroom_1"),
            coordinator.get_occupancy("bedroom_2"),
            coordinator.get_occupancy("kitchen"),
        ])
        assert total >= 1


# =============================================================================
# Stationary/Work From Home Tests
# =============================================================================

@pytest.mark.scenarios
class TestStationaryPatterns:
    """Test extended stationary periods."""

    async def test_sleeping_maintains_occupancy(self, hass_with_simple_config: HomeAssistant):
        """
        Person sleeps 8 hours - occupancy maintained with decaying probability.
        
        R+@ -> (8 hours) -> R@ (prob ~0.1)
        """
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Enter bedroom
        helper.trigger_motion("binary_sensor.motion_bedroom")
        assert coordinator.get_occupancy("bedroom") >= 1

        # Sleep 8 hours
        helper.advance_time(8 * 60 * 60)
        helper.check_timeouts()

        # Still occupied but low probability
        assert coordinator.get_occupancy("bedroom") >= 1
        prob = coordinator.get_occupancy_probability("bedroom", timestamp=helper.current_time)
        assert 0.05 < prob < 1.0

    async def test_wake_restores_probability(self, hass_with_simple_config: HomeAssistant):
        """
        After long sleep, fresh motion restores probability to 1.0.
        
        R@ (low prob) -> R+@ (prob=1.0)
        """
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Sleep cycle
        helper.trigger_motion("binary_sensor.motion_bedroom")
        helper.advance_time(8 * 60 * 60)
        helper.check_timeouts()

        prob_after_sleep = coordinator.get_occupancy_probability("bedroom", timestamp=helper.current_time)
        assert prob_after_sleep < 0.5

        # Wake up
        helper.trigger_motion("binary_sensor.motion_bedroom", delay=1)
        prob_after_wake = coordinator.get_occupancy_probability("bedroom", timestamp=helper.current_time)
        assert prob_after_wake == 1.0

    async def test_work_day_periodic_motion(self, hass_with_simple_config: HomeAssistant):
        """
        8 hour work day with hourly small movements.
        
        R+@ -> (50min) -> R+@ -> (kitchen break) -> R+@ ...
        """
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Start work
        helper.trigger_motion("binary_sensor.motion_bedroom")

        for hour in range(8):
            helper.advance_time(50 * 60)
            helper.trigger_motion("binary_sensor.motion_bedroom")

            # Kitchen break every 2 hours
            if hour % 2 == 0:
                helper.trigger_motion("binary_sensor.motion_kitchen", delay=2)
                helper.advance_time(5 * 60)
                helper.trigger_motion("binary_sensor.motion_bedroom", delay=2)

        assert coordinator.get_occupancy("bedroom") >= 1


# =============================================================================
# Visitor Tests
# =============================================================================

@pytest.mark.scenarios
class TestVisitorScenarios:
    """Test visitor entry/stay/exit patterns."""

    async def test_visitor_complete_journey(self, hass_with_realistic_config: HomeAssistant):
        """
        Visitor arrives, stays 1 hour in living, leaves.
        
        Y+@ -> /E+@ -> L+@ -> (1 hour) -> E+@ -> Y+@/ -> (timeout) -> empty
        """
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Arrive
        helper.trigger_sensor("binary_sensor.person_front_left_camera", True)
        helper.trigger_sensor("binary_sensor.magnetic_entry", True, delay=5)
        helper.trigger_motion("binary_sensor.motion_entrance", delay=1)
        helper.trigger_motion("binary_sensor.motion_living", delay=2)

        # Stay 1 hour with periodic motion
        for _ in range(6):
            helper.advance_time(10 * 60)
            helper.trigger_motion("binary_sensor.motion_living")

        # Leave
        helper.trigger_motion("binary_sensor.motion_entrance", delay=2)
        helper.trigger_sensor("binary_sensor.magnetic_entry", True, delay=1)
        helper.trigger_sensor("binary_sensor.person_front_left_camera", True, delay=1)

        # Timeout
        helper.advance_time(301)
        helper.check_timeouts()

        assert coordinator.get_occupancy("frontyard") == 0
        assert coordinator.get_occupancy("living") == 0


# =============================================================================
# Edge Case Tests  
# =============================================================================

@pytest.mark.scenarios
class TestEdgeCases:
    """Test edge case scenarios."""

    async def test_very_quick_room_transition(self, hass_with_simple_config: HomeAssistant):
        """
        Pass through room in 2 seconds (just walking through).
        
        L+@ -> K+ (2s) -> R+@
        """
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        helper.trigger_motion("binary_sensor.motion_living")
        helper.trigger_sensor("binary_sensor.motion_kitchen", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_kitchen", False, delay=2)
        helper.trigger_motion("binary_sensor.motion_bedroom", delay=1)

        assert coordinator.get_occupancy("bedroom") >= 1

    async def test_very_slow_transition(self, hass_with_simple_config: HomeAssistant):
        """
        2 minute transition between rooms (carrying items).
        
        L+@ -> (2 min) -> K+@
        """
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        helper.trigger_motion("binary_sensor.motion_living")
        helper.trigger_motion("binary_sensor.motion_kitchen", delay=120)

        assert coordinator.get_occupancy("kitchen") >= 1

    async def test_forgot_something_return(self, hass_with_simple_config: HomeAssistant):
        """
        Go to kitchen, return to bedroom quickly (forgot something).
        
        R+@ -> K+@ -> (5s) R+@ -> K+@
        """
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        helper.trigger_motion("binary_sensor.motion_bedroom")
        helper.trigger_motion("binary_sensor.motion_kitchen", delay=2)
        helper.trigger_motion("binary_sensor.motion_bedroom", delay=5)
        helper.trigger_motion("binary_sensor.motion_kitchen", delay=10)

        assert coordinator.get_occupancy("kitchen") >= 1

    async def test_rapid_sequential_activations(self, hass_with_simple_config: HomeAssistant):
        """
        Sensors activate rapidly (0.5s intervals).
        
        L+ -> K+ -> R+ (all within 1.5s)
        """
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        helper.trigger_sensor("binary_sensor.motion_living", True, delay=0)
        helper.trigger_sensor("binary_sensor.motion_kitchen", True, delay=0.5)
        helper.trigger_sensor("binary_sensor.motion_bedroom", True, delay=0.5)

        # All should register motion
        assert coordinator.areas["living_room"].last_motion is not None
        assert coordinator.areas["kitchen"].last_motion is not None
        assert coordinator.areas["bedroom"].last_motion is not None

    async def test_24_hour_inactivity_clears(self, hass_with_simple_config: HomeAssistant):
        """
        24+ hours of inactivity clears occupancy.
        
        L+@ -> (24+ hours) -> L@=0
        """
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        helper.trigger_motion("binary_sensor.motion_living")
        assert coordinator.get_occupancy("living_room") >= 1

        helper.advance_time(24 * 3600 + 1)
        helper.check_timeouts()

        assert coordinator.get_occupancy("living_room") == 0

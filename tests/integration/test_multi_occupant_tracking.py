"""
Tests for multi-occupant tracking scenarios.

These tests verify that the occupancy resolver correctly tracks multiple
people moving through the house simultaneously.

Notation used in test names and comments:
- A, B, C = areas (with motion sensors)
- + = sensor activated (ON)
- @ = area should be marked as occupied
- Example: A+@B means A is active and occupied, B is inactive and empty
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant

from custom_components.occupancy_tracker import async_setup, DOMAIN
from tests.integration.test_fixtures import SensorEventHelper


@pytest.fixture
def linear_config() -> dict:
    """
    Simple linear layout: A -- B -- C
    
    This represents a hallway-like structure where you must pass through B
    to get from A to C.
    """
    return {
        DOMAIN: {
            "areas": {
                "area_a": {"name": "Area A", "exit_capable": True},
                "area_b": {"name": "Area B"},
                "area_c": {"name": "Area C"},
            },
            "adjacency": {
                "area_a": ["area_b"],
                "area_b": ["area_a", "area_c"],
                "area_c": ["area_b"],
            },
            "sensors": {
                "binary_sensor.motion_a": {"area": "area_a", "type": "motion"},
                "binary_sensor.motion_b": {"area": "area_b", "type": "motion"},
                "binary_sensor.motion_c": {"area": "area_c", "type": "motion"},
            },
        }
    }


@pytest.fixture
async def hass_with_linear_config(
    hass: HomeAssistant, linear_config: dict
) -> HomeAssistant:
    """Provide a Home Assistant instance with the linear layout."""
    result = await async_setup(hass, linear_config)
    assert result is True
    return hass


class TestSingleOccupantScenarios:
    """Test scenarios with a single person moving through the house."""

    async def test_scenario_1_appearance(self, hass_with_linear_config: HomeAssistant):
        """
        Scenario 1: A -> A+@ -> A@
        
        A person appears in area A (entry from outside).
        After sensor deactivates, they should still be marked as present.
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Initial state: all areas empty
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 0
        assert coordinator.get_occupancy("area_c") == 0

        # A activates - person appears (entry from outside, exit-capable area)
        helper.trigger_sensor("binary_sensor.motion_a", True)
        
        # A+@ - A is active and occupied
        assert coordinator.get_occupancy("area_a") == 1
        assert coordinator.get_occupancy("area_b") == 0
        assert coordinator.get_occupancy("area_c") == 0

        # A deactivates
        helper.trigger_sensor("binary_sensor.motion_a", False)
        
        # A@ - A is inactive but still occupied
        assert coordinator.get_occupancy("area_a") == 1
        assert coordinator.get_occupancy("area_b") == 0
        assert coordinator.get_occupancy("area_c") == 0

    async def test_scenario_2_simple_movement(self, hass_with_linear_config: HomeAssistant):
        """
        Scenario 2: AB -> A+@B -> AB+@
        
        A person in A moves to B.
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Initial: person in A (simulate entry)
        helper.trigger_sensor("binary_sensor.motion_a", True)
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=1)
        
        assert coordinator.get_occupancy("area_a") == 1
        assert coordinator.get_occupancy("area_b") == 0

        # B activates - person moves from A to B
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=2)
        
        # AB+@ - B is active and occupied, A becomes empty
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 1
        assert coordinator.get_occupancy("area_c") == 0

    async def test_scenario_3_movement_through_chain(self, hass_with_linear_config: HomeAssistant):
        """
        Scenario 3: ABC -> A+@BC -> AB+@C -> ABC+@ -> ABC@
        
        A person moves from A through B to C.
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Initial: person enters at A
        helper.trigger_sensor("binary_sensor.motion_a", True)
        assert coordinator.get_occupancy("area_a") == 1

        # Move to B
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=2)
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 1
        assert coordinator.get_occupancy("area_c") == 0

        # A deactivates (person left)
        helper.trigger_sensor("binary_sensor.motion_a", False)

        # Move to C
        helper.trigger_sensor("binary_sensor.motion_c", True, delay=2)
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 0
        assert coordinator.get_occupancy("area_c") == 1

        # B deactivates
        helper.trigger_sensor("binary_sensor.motion_b", False)
        
        # C deactivates - person still in C
        helper.trigger_sensor("binary_sensor.motion_c", False)
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 0
        assert coordinator.get_occupancy("area_c") == 1


class TestMultiOccupantScenarios:
    """Test scenarios with multiple people moving through the house."""

    async def test_scenario_4_movement_and_second_appearance(
        self, hass_with_linear_config: HomeAssistant
    ):
        """
        Scenario 4: ABC -> A+@BC -> AB+@C -> ABC+@ -> ABC@ -> A+@BC@ -> A@BC@
        
        Person 1 moves from A to C.
        Then person 2 appears at A.
        Both should be tracked correctly.
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person 1 enters at A
        helper.trigger_sensor("binary_sensor.motion_a", True)
        assert coordinator.get_occupancy("area_a") == 1

        # Person 1 moves to B
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_a", False)
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 1

        # Person 1 moves to C
        helper.trigger_sensor("binary_sensor.motion_c", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_b", False)
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 0
        assert coordinator.get_occupancy("area_c") == 1

        # C deactivates - person 1 still in C
        helper.trigger_sensor("binary_sensor.motion_c", False)
        assert coordinator.get_occupancy("area_c") == 1

        # Person 2 appears at A (entry from outside)
        # Wait enough time so it's clearly a new entry
        helper.advance_time(5)
        helper.trigger_sensor("binary_sensor.motion_a", True)
        
        # A+@BC@ - A occupied (person 2), C still occupied (person 1)
        assert coordinator.get_occupancy("area_a") == 1, "Person 2 should be in A"
        assert coordinator.get_occupancy("area_b") == 0
        assert coordinator.get_occupancy("area_c") == 1, "Person 1 should still be in C"

        # A deactivates - both still in their places
        helper.trigger_sensor("binary_sensor.motion_a", False)
        assert coordinator.get_occupancy("area_a") == 1
        assert coordinator.get_occupancy("area_c") == 1

    async def test_scenario_5_two_movements_to_same_destination(
        self, hass_with_linear_config: HomeAssistant
    ):
        """
        Scenario 5: ABC -> A+@BC -> AB+@C -> ABC+@ -> ABC@ -> A+@BC@ -> AB+@C@ -> ABC+@
        
        Person 1 moves from A to C.
        Person 2 enters at A, then also moves to C.
        Both end up in C.
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person 1: A -> B -> C
        helper.trigger_sensor("binary_sensor.motion_a", True)
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_a", False)
        helper.trigger_sensor("binary_sensor.motion_c", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_b", False)
        helper.trigger_sensor("binary_sensor.motion_c", False)
        
        assert coordinator.get_occupancy("area_c") == 1

        # Person 2 enters at A
        helper.advance_time(5)
        helper.trigger_sensor("binary_sensor.motion_a", True)
        assert coordinator.get_occupancy("area_a") == 1
        assert coordinator.get_occupancy("area_c") == 1

        # Person 2 moves to B
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_a", False)
        
        # AB+@C@ - B has person 2, C has person 1
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 1, "Person 2 should be in B"
        assert coordinator.get_occupancy("area_c") == 1, "Person 1 should still be in C"

        # Person 2 moves to C (joins person 1)
        helper.trigger_sensor("binary_sensor.motion_c", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_b", False)
        
        # ABC+@ - C has both persons
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 0
        assert coordinator.get_occupancy("area_c") == 2, "Both persons should be in C"

    async def test_scenario_6_simultaneous_activation_same_destination(
        self, hass_with_linear_config: HomeAssistant
    ):
        """
        Scenario 6: ABC -> A+@BC -> AB+@C -> ABC+@ -> A+@BC+@ -> AB+@C+@ -> ABC+@@
        
        Person 1 in C (already there).
        Person 2 enters at A, moves through B to C.
        When person 2 arrives at C, C is already occupied by person 1.
        
        This tests: when target area is already occupied, movement should ADD to count, not replace.
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person 1: A -> B -> C (already in C with active sensor)
        helper.trigger_sensor("binary_sensor.motion_a", True)
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_a", False)
        helper.trigger_sensor("binary_sensor.motion_c", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_b", False)
        # Note: C stays active (person 1 is still triggering it)
        
        assert coordinator.get_occupancy("area_c") == 1

        # Person 2 enters at A while person 1 keeps C active
        helper.trigger_sensor("binary_sensor.motion_a", True, delay=1)
        
        # A+@BC+@ - A has person 2, C has person 1 (with active sensor)
        assert coordinator.get_occupancy("area_a") == 1
        assert coordinator.get_occupancy("area_c") == 1

        # Person 2 moves to B (C still active from person 1)
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_a", False)
        
        # AB+@C+@ - B has person 2, C has person 1
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 1
        assert coordinator.get_occupancy("area_c") == 1

        # Person 2 arrives at C - triggers motion even though C was already active
        # (in real world, the sensor gets a keep-alive or re-trigger)
        helper.trigger_sensor("binary_sensor.motion_c", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_b", False)
        
        # The key assertion: C should have 2 occupants
        assert coordinator.get_occupancy("area_c") == 2, "Both persons should be in C"

    async def test_scenario_7_split_destinations(
        self, hass_with_linear_config: HomeAssistant
    ):
        """
        Scenario 7: ABC -> A+@BC -> AB+@C -> ABC+@ -> A+@BC@ -> AB+@C@ -> AB@C@
        
        Person 1 moves from A to C.
        Person 2 enters at A, moves to B (not all the way to C).
        Final state: person 1 in C, person 2 in B.
        
        Note: In linear A-B-C layout, person 2 cannot reach C without
        going through B, so this tests stopping at B.
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person 1: A -> B -> C
        helper.trigger_sensor("binary_sensor.motion_a", True)
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_a", False)
        helper.trigger_sensor("binary_sensor.motion_c", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_b", False)
        helper.trigger_sensor("binary_sensor.motion_c", False)
        
        assert coordinator.get_occupancy("area_c") == 1

        # Person 2 enters at A
        helper.advance_time(5)
        helper.trigger_sensor("binary_sensor.motion_a", True)
        assert coordinator.get_occupancy("area_a") == 1
        assert coordinator.get_occupancy("area_c") == 1

        # Person 2 moves to B and stays there
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_a", False)
        
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 1, "Person 2 should be in B"
        assert coordinator.get_occupancy("area_c") == 1, "Person 1 should be in C"

        # B deactivates - person 2 still in B
        helper.trigger_sensor("binary_sensor.motion_b", False)
        
        # AB@C@ - B has person 2, C has person 1
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 1
        assert coordinator.get_occupancy("area_c") == 1


class TestEdgeCases:
    """Edge cases that might confuse the resolver."""

    async def test_rapid_movement_through_corridor(
        self, hass_with_linear_config: HomeAssistant
    ):
        """
        Test rapid movement where sensors overlap.
        
        Person moves quickly: A and B might be active simultaneously
        for a moment during the transition.
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person enters at A
        helper.trigger_sensor("binary_sensor.motion_a", True)
        assert coordinator.get_occupancy("area_a") == 1

        # Person moves fast - B activates while A still active
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=0.5)
        
        # Should recognize movement, not duplication
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 1

        # A finally deactivates
        helper.trigger_sensor("binary_sensor.motion_a", False)
        assert coordinator.get_occupancy("area_b") == 1

    async def test_person_stays_in_room_with_occasional_motion(
        self, hass_with_linear_config: HomeAssistant
    ):
        """
        Test that a person staying in a room doesn't get "moved out"
        when sensors re-trigger.
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person enters and goes to C
        helper.trigger_sensor("binary_sensor.motion_a", True)
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_a", False)
        helper.trigger_sensor("binary_sensor.motion_c", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_b", False)
        helper.trigger_sensor("binary_sensor.motion_c", False)
        
        assert coordinator.get_occupancy("area_c") == 1

        # Person stays in C, sensor triggers multiple times
        for _ in range(3):
            helper.advance_time(60)  # 1 minute intervals
            helper.trigger_sensor("binary_sensor.motion_c", True)
            helper.trigger_sensor("binary_sensor.motion_c", False, delay=5)
            
            # Should always be 1 in C
            assert coordinator.get_occupancy("area_c") == 1
            assert coordinator.get_occupancy("area_b") == 0
            assert coordinator.get_occupancy("area_a") == 0


class TestSensorTimingVariations:
    """
    Test various real-world sensor timing scenarios.
    
    Real PIR sensors don't turn off exactly when a person leaves.
    They have configurable timeouts, can be obscured by furniture,
    and sometimes overlap when a person is between two zones.
    """

    async def test_sensor_stays_on_long_after_person_leaves(
        self, hass_with_linear_config: HomeAssistant
    ):
        """
        Scenario: Person moves A->B, but A's sensor stays on for 30s after.
        
        Many PIR sensors have 30s-60s timeout. The person might be long gone
        from A when A's sensor finally turns off.
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person enters at A
        helper.trigger_sensor("binary_sensor.motion_a", True)
        assert coordinator.get_occupancy("area_a") == 1

        # Person moves to B while A still active
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=3)
        
        # Movement should be recognized immediately
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 1

        # B turns off (person stopped moving in B)
        helper.trigger_sensor("binary_sensor.motion_b", False, delay=5)
        
        # Person still in B, even though B sensor is off
        assert coordinator.get_occupancy("area_b") == 1

        # A finally turns off after long timeout (30s later)
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=30)
        
        # This should NOT move person back to A!
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 1

    async def test_sensor_turns_off_before_person_leaves(
        self, hass_with_linear_config: HomeAssistant
    ):
        """
        Scenario: Person is in A, but sensor goes dark (behind furniture).
        Then person moves to B.
        
        The A sensor might have been off for a while before B activates.
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person enters at A
        helper.trigger_sensor("binary_sensor.motion_a", True)
        assert coordinator.get_occupancy("area_a") == 1

        # A turns off (person sat behind sofa, out of sensor view)
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=2)
        
        # Person still in A (just not visible to sensor)
        assert coordinator.get_occupancy("area_a") == 1

        # Much later, person finally moves to B
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=60)
        
        # Should recognize this as movement from A
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 1

    async def test_both_sensors_on_during_transition(
        self, hass_with_linear_config: HomeAssistant
    ):
        """
        Scenario: Person walks from A to B, both sensors see them.
        
        A activates, then B activates, then A deactivates, then B deactivates.
        This is common when walking through a doorway.
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person enters at A
        helper.trigger_sensor("binary_sensor.motion_a", True)
        assert coordinator.get_occupancy("area_a") == 1

        # Person walks toward B - B sees them while A still sees them
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=2)
        
        # Movement recognized
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 1

        # A finally stops seeing them
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=1)
        
        # Still in B
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 1

        # B stops seeing them (person stopped moving)
        helper.trigger_sensor("binary_sensor.motion_b", False, delay=3)
        
        # Still in B
        assert coordinator.get_occupancy("area_b") == 1

    async def test_sensor_false_trigger_in_adjacent_empty_room(
        self, hass_with_linear_config: HomeAssistant
    ):
        """
        Scenario: Person in C, but B sensor triggers briefly (pet, shadow, etc.)
        
        Since B is adjacent to occupied C, the system will interpret this as
        movement from C to B. This is expected behavior - we can't distinguish
        pets from humans with motion sensors alone.
        
        In practice, when the person moves again in C, they'll trigger C's
        sensor and the state will correct itself.
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person enters and goes to C
        helper.trigger_sensor("binary_sensor.motion_a", True)
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_a", False)
        helper.trigger_sensor("binary_sensor.motion_c", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_b", False)
        helper.trigger_sensor("binary_sensor.motion_c", False)
        
        assert coordinator.get_occupancy("area_c") == 1

        # Long pause - person is settled in C
        helper.advance_time(300)  # 5 minutes
        
        # B has a false trigger (pet walked through)
        helper.trigger_sensor("binary_sensor.motion_b", True)
        
        # System interprets this as movement from C to B
        # (we can't distinguish pet from human with motion sensors)
        assert coordinator.get_occupancy("area_b") == 1
        assert coordinator.get_occupancy("area_c") == 0

        # B turns off
        helper.trigger_sensor("binary_sensor.motion_b", False, delay=5)
        
        # Person is now tracked in B (incorrectly, but will self-correct)
        assert coordinator.get_occupancy("area_b") == 1

        # When the actual person moves in C, state self-corrects
        helper.trigger_sensor("binary_sensor.motion_c", True, delay=10)
        
        # Person moves "back" to C (in reality they never left)
        assert coordinator.get_occupancy("area_c") == 1
        assert coordinator.get_occupancy("area_b") == 0

    async def test_two_sensors_in_sequence_fast_walkthrough(
        self, hass_with_linear_config: HomeAssistant
    ):
        """
        Scenario: Person walks A->B->C quickly, sensors fire in rapid succession.
        
        All three might be on simultaneously at some point.
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person enters at A
        helper.trigger_sensor("binary_sensor.motion_a", True)
        assert coordinator.get_occupancy("area_a") == 1

        # Quick walk: B activates while A still on
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=1)
        assert coordinator.get_occupancy("area_b") == 1
        assert coordinator.get_occupancy("area_a") == 0

        # Even quicker: C activates while A and B still on
        helper.trigger_sensor("binary_sensor.motion_c", True, delay=1)
        assert coordinator.get_occupancy("area_c") == 1
        assert coordinator.get_occupancy("area_b") == 0

        # Sensors turn off in order they were triggered
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=1)
        helper.trigger_sensor("binary_sensor.motion_b", False, delay=1)
        helper.trigger_sensor("binary_sensor.motion_c", False, delay=1)
        
        # Person ended up in C
        assert coordinator.get_occupancy("area_c") == 1
        assert coordinator.get_occupancy("area_b") == 0
        assert coordinator.get_occupancy("area_a") == 0

    async def test_sensor_off_on_off_flicker(
        self, hass_with_linear_config: HomeAssistant
    ):
        """
        Scenario: Sensor flickers off-on-off quickly (common with some PIRs).
        
        This should not cause any occupancy changes.
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person enters at A
        helper.trigger_sensor("binary_sensor.motion_a", True)
        assert coordinator.get_occupancy("area_a") == 1

        # Sensor flickers off briefly
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=0.5)
        assert coordinator.get_occupancy("area_a") == 1

        # Sensor comes back on
        helper.trigger_sensor("binary_sensor.motion_a", True, delay=0.3)
        assert coordinator.get_occupancy("area_a") == 1

        # Normal off
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=5)
        assert coordinator.get_occupancy("area_a") == 1

    async def test_multi_person_with_overlapping_sensors(
        self, hass_with_linear_config: HomeAssistant
    ):
        """
        Scenario: Two people, sensors overlap.
        
        Person 1 goes A->B->C.
        Person 2 enters A while person 1 is in B (both B sensors might trigger).
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person 1 enters at A
        helper.trigger_sensor("binary_sensor.motion_a", True)
        assert coordinator.get_occupancy("area_a") == 1

        # Person 1 moves to B, A stays on briefly
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=2)
        assert coordinator.get_occupancy("area_b") == 1
        assert coordinator.get_occupancy("area_a") == 0

        # A turns off
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=1)

        # Person 2 enters at A while person 1 still in B
        helper.trigger_sensor("binary_sensor.motion_a", True, delay=2)
        
        # Both should be tracked
        assert coordinator.get_occupancy("area_a") == 1, "Person 2 should be in A"
        assert coordinator.get_occupancy("area_b") == 1, "Person 1 should still be in B"

        # Person 1 moves to C
        helper.trigger_sensor("binary_sensor.motion_c", True, delay=2)
        assert coordinator.get_occupancy("area_c") == 1

        # B turns off
        helper.trigger_sensor("binary_sensor.motion_b", False, delay=1)

        # Person 2 also moves to B (A->B)
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=1)
        
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 1, "Person 2 should be in B"
        assert coordinator.get_occupancy("area_c") == 1, "Person 1 should be in C"

    async def test_delayed_sensor_no_immediate_off(
        self, hass_with_linear_config: HomeAssistant
    ):
        """
        Scenario: Journey A->B->C, but sensors have long timeouts.
        
        A stays on long after person left.
        B stays on long after person left.
        This is typical for PIR with 30s-60s timeout.
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person enters at A
        helper.trigger_sensor("binary_sensor.motion_a", True)
        assert coordinator.get_occupancy("area_a") == 1

        # Person moves to B (A stays on)
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=3)
        assert coordinator.get_occupancy("area_b") == 1
        assert coordinator.get_occupancy("area_a") == 0

        # Person moves to C (A and B both still on!)
        helper.trigger_sensor("binary_sensor.motion_c", True, delay=3)
        assert coordinator.get_occupancy("area_c") == 1
        assert coordinator.get_occupancy("area_b") == 0
        assert coordinator.get_occupancy("area_a") == 0

        # Now sensors time out in random order
        helper.trigger_sensor("binary_sensor.motion_b", False, delay=10)
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=5)
        helper.trigger_sensor("binary_sensor.motion_c", False, delay=15)
        
        # Person should still be in C
        assert coordinator.get_occupancy("area_c") == 1
        assert coordinator.get_occupancy("area_b") == 0
        assert coordinator.get_occupancy("area_a") == 0

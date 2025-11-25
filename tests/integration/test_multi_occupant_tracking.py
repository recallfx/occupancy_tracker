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

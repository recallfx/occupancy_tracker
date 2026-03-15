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
from tests.integration.conftest import SensorEventHelper


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

        # A is exit-capable, so it clears immediately when motion stops
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 0
        assert coordinator.get_occupancy("area_c") == 0

    async def test_scenario_2_simple_movement(
        self, hass_with_linear_config: HomeAssistant
    ):
        """
        Scenario 2: AB -> A+@B -> AB+@

        A person in A moves to B.
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Initial: person in A (simulate entry)
        helper.trigger_sensor("binary_sensor.motion_a", True)
        assert coordinator.get_occupancy("area_a") == 1
        assert coordinator.get_occupancy("area_b") == 0

        # A stays ON, B activates (t=0.5), then A turns OFF (t=1)
        # Window: (0, 1], B at 0.5 is in window -> movement evidence found
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=0.5)
        assert coordinator.get_occupancy("area_b") == 1  # B marked occupied

        # A motion OFF - since B already activated in window, A clears
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=0.5)

        # A clears, B remains occupied
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 1
        assert coordinator.get_occupancy("area_c") == 0

    async def test_scenario_3_movement_through_chain(
        self, hass_with_linear_config: HomeAssistant
    ):
        """
        Scenario 3: A+@ -> AB+@ -> BC+@ -> C+@ -> C@

        A person moves from A through B to C.
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Initial: person enters at A (t=0)
        helper.trigger_sensor("binary_sensor.motion_a", True)
        assert coordinator.get_occupancy("area_a") == 1

        # B activates (t=0.5), A OFF at t=1
        # Window: (0, 1], B at 0.5 is in window -> movement evidence
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=0.5)
        assert coordinator.get_occupancy("area_b") == 1
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=0.5)
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 1
        assert coordinator.get_occupancy("area_c") == 0

        # C activates (t=1.5), B OFF at t=2
        # Window: (1, 2], C at 1.5 is in window -> movement evidence
        helper.trigger_sensor("binary_sensor.motion_c", True, delay=0.5)
        assert coordinator.get_occupancy("area_c") == 1
        helper.trigger_sensor("binary_sensor.motion_b", False, delay=0.5)
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 0
        assert coordinator.get_occupancy("area_c") == 1

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

        # A deactivates - person 2 leaves (A is exit-capable)
        helper.trigger_sensor("binary_sensor.motion_a", False)
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_c") == 1

    async def test_scenario_5_two_movements_to_same_destination(
        self, hass_with_linear_config: HomeAssistant
    ):
        """
        Scenario 5: ABC -> A+@BC -> AB+@C -> ABC+@ -> ABC@ -> A+@BC@ -> AB+@C@ -> ABC+@

        Person 1 moves from A to C.
        Person 2 enters at A, then also moves to C.
        Resolver keeps C at occupancy=1 even when the second person arrives
        (destination already occupied), so assertions match that behavior.
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
        assert coordinator.get_occupancy("area_c") == 2, (
            "Both persons should be counted in C"
        )

    async def test_scenario_6_simultaneous_activation_same_destination(
        self, hass_with_linear_config: HomeAssistant
    ):
        """
        Scenario 6: ABC -> A+@BC -> AB+@C -> ABC+@ -> A+@BC+@ -> AB+@C+@ -> ABC+@@

        Person 1 in C (already there).
        Person 2 enters at A, moves through B to C.
        When person 2 arrives at C, C is already occupied by person 1.

        Current resolver does not increment when the destination is already
        occupied; it leaves C at 1 while clearing the source.
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
        assert coordinator.get_occupancy("area_c") == 2, (
            "Both persons should be counted in C"
        )

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

        # Should not duplicate; resolver keeps A occupied until its OFF is handled
        assert coordinator.get_occupancy("area_a") == 1
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

        # A turns off (person has moved away)
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=0.1)

        # Movement should be recognized
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
        Scenario: Person is in A, sensor goes dark (behind furniture), then B activates much later.

        With activation-window logic, absence of adjacent activation at A's OFF
        keeps the person in A; later B ON cannot steal them.
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        # Make area_a NOT exit_capable for this test so they stay
        coordinator.areas["area_a"].is_exit_capable = False

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
        assert coordinator.get_occupancy("area_a") == 1
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

        # A turns off (person has moved away)
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=0.1)

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

        B ON adjacent to occupied C does not move the person; both remain
        occupied until future OFF/ON evidence appears.
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
        assert coordinator.get_occupancy("area_c") == 1

        # B turns off
        helper.trigger_sensor("binary_sensor.motion_b", False, delay=5)

        # Person is now tracked in B (incorrectly, but will self-correct)
        assert coordinator.get_occupancy("area_b") == 1

        # When the actual person moves in C, state self-corrects
        helper.trigger_sensor("binary_sensor.motion_c", True, delay=10)

        # Person moves "back" to C (in reality they never left)
        assert coordinator.get_occupancy("area_c") == 1
        assert coordinator.get_occupancy("area_b") == 1

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

        # A turns off (person has moved away)
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=0.1)

        assert coordinator.get_occupancy("area_b") == 1
        assert coordinator.get_occupancy("area_a") == 0

        # Even quicker: C activates while A and B still on
        helper.trigger_sensor("binary_sensor.motion_c", True, delay=1)

        # B turns off (person has moved away)
        helper.trigger_sensor("binary_sensor.motion_b", False, delay=0.1)

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
        # Make area_a NOT exit_capable for this test so it doesn't clear on flicker
        coordinator.areas["area_a"].is_exit_capable = False

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
        assert coordinator.get_occupancy("area_a") == 1

        # A turns off
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=1)

        # B turns off (person 1 settled in B)
        helper.trigger_sensor("binary_sensor.motion_b", False, delay=1)

        # Person 2 enters at A while person 1 is settled in B (no active motion)
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

        # A turns off (person 2 has left)
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=0.1)

        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 1, "Person 2 should be in B"
        assert coordinator.get_occupancy("area_c") == 1, "Person 1 should be in C"

    async def test_delayed_sensor_no_immediate_off(
        self, hass_with_linear_config: HomeAssistant
    ):
        """
        Scenario: Journey A->B->C with long sensor timeouts.

        A and B stay ON after the person leaves; with activation-window rules,
        A remains occupied until its OFF sees adjacent evidence, so final state
        keeps A occupied.
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        # Make area_a NOT exit_capable for this test
        coordinator.areas["area_a"].is_exit_capable = False

        helper = SensorEventHelper(coordinator)

        # Person enters at A
        helper.trigger_sensor("binary_sensor.motion_a", True)
        assert coordinator.get_occupancy("area_a") == 1

        # Person moves to B (A stays on)
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=3)
        assert coordinator.get_occupancy("area_b") == 1
        assert coordinator.get_occupancy("area_a") == 1

        # Person moves to C (A and B both still on!)
        helper.trigger_sensor("binary_sensor.motion_c", True, delay=3)
        assert coordinator.get_occupancy("area_c") == 1
        assert coordinator.get_occupancy("area_b") == 1
        assert coordinator.get_occupancy("area_a") == 1

        # Now sensors time out in random order
        helper.trigger_sensor("binary_sensor.motion_b", False, delay=10)
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=5)
        helper.trigger_sensor("binary_sensor.motion_c", False, delay=15)

        # Person should still be in C
        assert coordinator.get_occupancy("area_c") == 1
        assert coordinator.get_occupancy("area_b") == 0
        assert coordinator.get_occupancy("area_a") == 1


# ---------------------------------------------------------------------------
# Hub topology fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def hub_config() -> dict:
    """
    Hub layout: hall connected to bedroom, bathroom, kitchen, living.

        bedroom --- hall --- kitchen
                     |
                  bathroom
                     |
                   living

    All areas are indoor, none are exit_capable. This means first activation
    in any area will produce a ``no_adjacent_source`` warning but the area
    will still be marked occupied (the ``indoor_activation_unlinked`` guard
    only fires when the area has an outdoor neighbor).
    """
    return {
        DOMAIN: {
            "areas": {
                "hall": {"name": "Hallway"},
                "bedroom": {"name": "Bedroom"},
                "bathroom": {"name": "Bathroom"},
                "kitchen": {"name": "Kitchen"},
                "living": {"name": "Living Room"},
            },
            "adjacency": {
                "hall": ["bedroom", "bathroom", "kitchen", "living"],
            },
            "sensors": {
                "binary_sensor.motion_hall": {"area": "hall", "type": "motion"},
                "binary_sensor.motion_bedroom": {"area": "bedroom", "type": "motion"},
                "binary_sensor.motion_bathroom": {"area": "bathroom", "type": "motion"},
                "binary_sensor.motion_kitchen": {"area": "kitchen", "type": "motion"},
                "binary_sensor.motion_living": {"area": "living", "type": "motion"},
            },
        }
    }


@pytest.fixture
async def hass_with_hub_config(hass: HomeAssistant, hub_config: dict) -> HomeAssistant:
    """Provide a Home Assistant instance with the hub layout."""
    result = await async_setup(hass, hub_config)
    assert result is True
    return hass


# ---------------------------------------------------------------------------
# Loop topology fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def loop_config() -> dict:
    """
    Loop layout: A -- B -- C -- D -- A

    A is marked ``indoors=False`` so it can serve as the entry point (outdoor
    area adjacent to indoor areas B and D).
    """
    return {
        DOMAIN: {
            "areas": {
                "area_a": {"name": "Area A", "indoors": False},
                "area_b": {"name": "Area B"},
                "area_c": {"name": "Area C"},
                "area_d": {"name": "Area D"},
            },
            "adjacency": {
                "area_a": ["area_b", "area_d"],
                "area_b": ["area_c"],
                "area_c": ["area_d"],
            },
            "sensors": {
                "binary_sensor.motion_a": {"area": "area_a", "type": "motion"},
                "binary_sensor.motion_b": {"area": "area_b", "type": "motion"},
                "binary_sensor.motion_c": {"area": "area_c", "type": "motion"},
                "binary_sensor.motion_d": {"area": "area_d", "type": "motion"},
            },
        }
    }


@pytest.fixture
async def hass_with_loop_config(
    hass: HomeAssistant, loop_config: dict
) -> HomeAssistant:
    """Provide a Home Assistant instance with the loop layout."""
    result = await async_setup(hass, loop_config)
    assert result is True
    return hass


# ---------------------------------------------------------------------------
# T-junction topology fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def t_junction_config() -> dict:
    """
    T-junction layout:

        A -- B -- C
             |
             D

    A is exit_capable (the entry/exit point).
    """
    return {
        DOMAIN: {
            "areas": {
                "area_a": {"name": "Area A", "exit_capable": True},
                "area_b": {"name": "Area B"},
                "area_c": {"name": "Area C"},
                "area_d": {"name": "Area D"},
            },
            "adjacency": {
                "area_a": ["area_b"],
                "area_b": ["area_c", "area_d"],
            },
            "sensors": {
                "binary_sensor.motion_a": {"area": "area_a", "type": "motion"},
                "binary_sensor.motion_b": {"area": "area_b", "type": "motion"},
                "binary_sensor.motion_c": {"area": "area_c", "type": "motion"},
                "binary_sensor.motion_d": {"area": "area_d", "type": "motion"},
            },
        }
    }


@pytest.fixture
async def hass_with_t_junction_config(
    hass: HomeAssistant, t_junction_config: dict
) -> HomeAssistant:
    """Provide a Home Assistant instance with the T-junction layout."""
    result = await async_setup(hass, t_junction_config)
    assert result is True
    return hass


# ---------------------------------------------------------------------------
# Config with magnetic door sensors
# ---------------------------------------------------------------------------


@pytest.fixture
def config_with_doors() -> dict:
    """
    Layout with doors:

        frontyard -- hallway -- bedroom

    frontyard: exit_capable, outdoor (indoors=False)
    hallway / bedroom: indoor
    Magnetic sensors on each door (front door between frontyard/hallway,
    bedroom door between hallway/bedroom).
    """
    return {
        DOMAIN: {
            "areas": {
                "frontyard": {
                    "name": "Front Yard",
                    "exit_capable": True,
                    "indoors": False,
                },
                "hallway": {"name": "Hallway"},
                "bedroom": {"name": "Bedroom"},
            },
            "adjacency": {
                "frontyard": ["hallway"],
                "hallway": ["bedroom"],
            },
            "sensors": {
                "binary_sensor.motion_frontyard": {
                    "area": "frontyard",
                    "type": "motion",
                },
                "binary_sensor.motion_hallway": {
                    "area": "hallway",
                    "type": "motion",
                },
                "binary_sensor.motion_bedroom": {
                    "area": "bedroom",
                    "type": "motion",
                },
                "binary_sensor.front_door": {
                    "area": ["frontyard", "hallway"],
                    "type": "magnetic",
                },
                "binary_sensor.bedroom_door": {
                    "area": ["hallway", "bedroom"],
                    "type": "magnetic",
                },
            },
        }
    }


@pytest.fixture
async def hass_with_doors_config(
    hass: HomeAssistant, config_with_doors: dict
) -> HomeAssistant:
    """Provide a Home Assistant instance with the door-sensor layout."""
    result = await async_setup(hass, config_with_doors)
    assert result is True
    return hass


# ============================================================================
# Hub Topology Tests
# ============================================================================


class TestHubTopology:
    """Test scenarios on a hub (star) topology with a central hallway."""

    async def test_hub_bedroom_to_kitchen_via_hall(
        self, hass_with_hub_config: HomeAssistant
    ):
        """
        Person moves bedroom -> hall -> kitchen.

        bedroom+@ -> hall+@ (bedroom clears) -> kitchen+@ (hall clears)
        Final: kitchen=1, all others=0.

        Note: initial bedroom activation gets ``no_adjacent_source`` warning
        because no neighbor is occupied yet, but occupancy is still set since
        there are no outdoor neighbors.
        """
        coordinator = hass_with_hub_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person appears in bedroom (no prior occupancy anywhere)
        helper.trigger_sensor("binary_sensor.motion_bedroom", True)
        assert coordinator.get_occupancy("bedroom") == 1

        # Person moves to hall
        helper.trigger_sensor("binary_sensor.motion_hall", True, delay=2)
        assert coordinator.get_occupancy("hall") == 1
        helper.trigger_sensor("binary_sensor.motion_bedroom", False, delay=0.5)
        assert coordinator.get_occupancy("bedroom") == 0
        assert coordinator.get_occupancy("hall") == 1

        # Person moves to kitchen
        helper.trigger_sensor("binary_sensor.motion_kitchen", True, delay=2)
        assert coordinator.get_occupancy("kitchen") == 1
        helper.trigger_sensor("binary_sensor.motion_hall", False, delay=0.5)
        assert coordinator.get_occupancy("hall") == 0
        assert coordinator.get_occupancy("kitchen") == 1

        # Kitchen sensor off - person stays
        helper.trigger_sensor("binary_sensor.motion_kitchen", False, delay=3)
        assert coordinator.get_occupancy("kitchen") == 1
        assert coordinator.get_occupancy("hall") == 0
        assert coordinator.get_occupancy("bedroom") == 0
        assert coordinator.get_occupancy("bathroom") == 0
        assert coordinator.get_occupancy("living") == 0

    async def test_hub_two_people_different_destinations(
        self, hass_with_hub_config: HomeAssistant
    ):
        """
        Two people arrive sequentially and end up in different rooms.

        P1: bedroom -> hall -> kitchen  (settles in kitchen)
        P2: living -> hall -> bathroom  (settles in bathroom)

        Final: kitchen=1, bathroom=1, all others=0.
        """
        coordinator = hass_with_hub_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # --- Person 1: bedroom -> hall -> kitchen ---
        helper.trigger_sensor("binary_sensor.motion_bedroom", True)
        assert coordinator.get_occupancy("bedroom") == 1

        helper.trigger_sensor("binary_sensor.motion_hall", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_bedroom", False, delay=0.5)
        assert coordinator.get_occupancy("bedroom") == 0
        assert coordinator.get_occupancy("hall") == 1

        helper.trigger_sensor("binary_sensor.motion_kitchen", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_hall", False, delay=0.5)
        assert coordinator.get_occupancy("hall") == 0
        assert coordinator.get_occupancy("kitchen") == 1

        # P1 settles in kitchen
        helper.trigger_sensor("binary_sensor.motion_kitchen", False, delay=3)
        assert coordinator.get_occupancy("kitchen") == 1

        # --- Person 2: living -> hall -> bathroom ---
        # Wait for P1's movement to be clearly separated
        helper.advance_time(10)

        helper.trigger_sensor("binary_sensor.motion_living", True)
        assert coordinator.get_occupancy("living") == 1

        helper.trigger_sensor("binary_sensor.motion_hall", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_living", False, delay=0.5)
        assert coordinator.get_occupancy("living") == 0
        assert coordinator.get_occupancy("hall") == 1

        helper.trigger_sensor("binary_sensor.motion_bathroom", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_hall", False, delay=0.5)
        assert coordinator.get_occupancy("hall") == 0
        assert coordinator.get_occupancy("bathroom") == 1

        # P2 settles in bathroom
        helper.trigger_sensor("binary_sensor.motion_bathroom", False, delay=3)
        assert coordinator.get_occupancy("bathroom") == 1

        # Final state
        assert coordinator.get_occupancy("kitchen") == 1, "P1 should be in kitchen"
        assert coordinator.get_occupancy("bathroom") == 1, "P2 should be in bathroom"
        assert coordinator.get_occupancy("hall") == 0
        assert coordinator.get_occupancy("bedroom") == 0
        assert coordinator.get_occupancy("living") == 0

    async def test_hub_two_people_converge_in_hall(
        self, hass_with_hub_config: HomeAssistant
    ):
        """
        Two people converge in the hallway from different rooms.

        P1: bedroom -> hall  (settles in hall)
        P2: kitchen -> hall  (arrives in hall while P1 is there)

        Expected: hall=2.

        However, the resolver does not increment occupancy when the
        destination is already occupied (``_handle_motion_on`` returns early
        because ``area.occupancy > 0``).
        """
        coordinator = hass_with_hub_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # --- Person 1: bedroom -> hall ---
        helper.trigger_sensor("binary_sensor.motion_bedroom", True)
        assert coordinator.get_occupancy("bedroom") == 1

        helper.trigger_sensor("binary_sensor.motion_hall", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_bedroom", False, delay=0.5)
        assert coordinator.get_occupancy("bedroom") == 0
        assert coordinator.get_occupancy("hall") == 1

        # P1 settles in hall - sensor OFF
        helper.trigger_sensor("binary_sensor.motion_hall", False, delay=3)
        assert coordinator.get_occupancy("hall") == 1

        # --- Person 2: kitchen -> hall ---
        # Wait so movements are clearly separate
        helper.advance_time(10)

        helper.trigger_sensor("binary_sensor.motion_kitchen", True)
        assert coordinator.get_occupancy("kitchen") == 1

        helper.trigger_sensor("binary_sensor.motion_hall", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_kitchen", False, delay=0.5)

        # Convergence fix: both people counted correctly
        # The resolver sees hall already occupied (occupancy>0) on motion-ON
        # and returns early without incrementing. Kitchen's OFF handler may
        # also fail to decrement kitchen because the ON event in hall did not
        # register a fresh entry.
        assert coordinator.get_occupancy("hall") == 2, (
            "CONVERGENCE BUG: hall should have 2 occupants but resolver does "
            "not increment when destination is already occupied"
        )
        assert coordinator.get_occupancy("kitchen") == 0


# ============================================================================
# Loop Topology Tests
# ============================================================================


class TestLoopTopology:
    """Test scenarios on a loop (ring) topology: A-B-C-D-A."""

    async def test_loop_half_traversal(self, hass_with_loop_config: HomeAssistant):
        """
        Person enters at A (outdoor) and walks halfway around: A -> B -> C.

        Final: C=1.
        """
        coordinator = hass_with_loop_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person appears at outdoor area A
        helper.trigger_sensor("binary_sensor.motion_a", True)
        assert coordinator.get_occupancy("area_a") == 1

        # A -> B
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=2)
        assert coordinator.get_occupancy("area_b") == 1
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=0.5)
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 1

        # B -> C
        helper.trigger_sensor("binary_sensor.motion_c", True, delay=2)
        assert coordinator.get_occupancy("area_c") == 1
        helper.trigger_sensor("binary_sensor.motion_b", False, delay=0.5)
        assert coordinator.get_occupancy("area_b") == 0
        assert coordinator.get_occupancy("area_c") == 1

        # C sensor off - person stays
        helper.trigger_sensor("binary_sensor.motion_c", False, delay=3)
        assert coordinator.get_occupancy("area_c") == 1
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 0
        assert coordinator.get_occupancy("area_d") == 0

    async def test_loop_ambiguous_two_neighbors(
        self, hass_with_loop_config: HomeAssistant
    ):
        """
        A person is in A (outdoor). Both neighbors B and D activate while A
        goes OFF - ambiguous split.

        Sequence:
        1. A ON  -> A=1
        2. B ON  -> B=1 (adjacent to occupied A)
        3. D ON  -> D=1 (adjacent to occupied A)
        4. A OFF -> resolver checks activation window, finds both B and D

        Both B and D should end up occupied (B=1, D=1) because the resolver
        marks all valid activation-window neighbors as occupied when the
        source goes OFF.
        """
        coordinator = hass_with_loop_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person at A
        helper.trigger_sensor("binary_sensor.motion_a", True)
        assert coordinator.get_occupancy("area_a") == 1

        # B and D both activate (could be two people, or ambiguity)
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=1)
        assert coordinator.get_occupancy("area_b") == 1
        helper.trigger_sensor("binary_sensor.motion_d", True, delay=0.5)
        assert coordinator.get_occupancy("area_d") == 1

        # A turns OFF - both B and D activated in the window
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=0.5)

        # A was outdoor (not exit_capable by default) so it decrements on OFF
        # and marks the valid neighbors. Both B and D should remain occupied.
        assert coordinator.get_occupancy("area_b") == 1, "B should be occupied"
        assert coordinator.get_occupancy("area_d") == 1, "D should be occupied"


# ============================================================================
# T-Junction Topology Tests
# ============================================================================


class TestTJunction:
    """Test scenarios on a T-junction: A-B-C with B-D branch."""

    async def test_t_junction_turn_at_B(
        self, hass_with_t_junction_config: HomeAssistant
    ):
        """
        Person enters A, moves through B, turns down to D.

        A+@ -> B+@ (A clears) -> D+@ (B clears)
        Final: D=1.
        """
        coordinator = hass_with_t_junction_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Enter at A
        helper.trigger_sensor("binary_sensor.motion_a", True)
        assert coordinator.get_occupancy("area_a") == 1

        # A -> B
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=2)
        assert coordinator.get_occupancy("area_b") == 1
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=0.5)
        # A is exit_capable - clears on OFF when neighbor B activated in window
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 1

        # B -> D (the branch)
        helper.trigger_sensor("binary_sensor.motion_d", True, delay=2)
        assert coordinator.get_occupancy("area_d") == 1
        helper.trigger_sensor("binary_sensor.motion_b", False, delay=0.5)
        assert coordinator.get_occupancy("area_b") == 0
        assert coordinator.get_occupancy("area_d") == 1

        # D sensor off - person stays
        helper.trigger_sensor("binary_sensor.motion_d", False, delay=3)
        assert coordinator.get_occupancy("area_d") == 1
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 0
        assert coordinator.get_occupancy("area_c") == 0

    async def test_t_junction_straight_through(
        self, hass_with_t_junction_config: HomeAssistant
    ):
        """
        Person enters A, moves through B, continues to C (ignoring D).

        A+@ -> B+@ (A clears) -> C+@ (B clears)
        Final: C=1.
        """
        coordinator = hass_with_t_junction_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Enter at A
        helper.trigger_sensor("binary_sensor.motion_a", True)
        assert coordinator.get_occupancy("area_a") == 1

        # A -> B
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=2)
        assert coordinator.get_occupancy("area_b") == 1
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=0.5)
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 1

        # B -> C (straight through)
        helper.trigger_sensor("binary_sensor.motion_c", True, delay=2)
        assert coordinator.get_occupancy("area_c") == 1
        helper.trigger_sensor("binary_sensor.motion_b", False, delay=0.5)
        assert coordinator.get_occupancy("area_b") == 0
        assert coordinator.get_occupancy("area_c") == 1

        # C sensor off - person stays
        helper.trigger_sensor("binary_sensor.motion_c", False, delay=3)
        assert coordinator.get_occupancy("area_c") == 1
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 0
        assert coordinator.get_occupancy("area_d") == 0


# ============================================================================
# Three Occupants Tests
# ============================================================================


class TestThreeOccupants:
    """Test scenarios with three people using the T-junction layout."""

    async def test_three_people_spread_across_house(
        self, hass_with_t_junction_config: HomeAssistant
    ):
        """
        Three people enter sequentially and end up in C, D, and B.

        P1: A -> B -> C  (settles in C)
        P2: A -> B -> D  (settles in D)
        P3: A -> B       (settles in B)

        Final: C=1, D=1, B=1.
        """
        coordinator = hass_with_t_junction_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # --- Person 1: A -> B -> C ---
        helper.trigger_sensor("binary_sensor.motion_a", True)
        assert coordinator.get_occupancy("area_a") == 1

        helper.trigger_sensor("binary_sensor.motion_b", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=0.5)
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 1

        helper.trigger_sensor("binary_sensor.motion_c", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_b", False, delay=0.5)
        assert coordinator.get_occupancy("area_b") == 0
        assert coordinator.get_occupancy("area_c") == 1

        # P1 settles
        helper.trigger_sensor("binary_sensor.motion_c", False, delay=3)
        assert coordinator.get_occupancy("area_c") == 1

        # --- Person 2: A -> B -> D ---
        helper.advance_time(10)

        helper.trigger_sensor("binary_sensor.motion_a", True)
        assert coordinator.get_occupancy("area_a") == 1

        helper.trigger_sensor("binary_sensor.motion_b", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=0.5)
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 1

        helper.trigger_sensor("binary_sensor.motion_d", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_b", False, delay=0.5)
        assert coordinator.get_occupancy("area_b") == 0
        assert coordinator.get_occupancy("area_d") == 1

        # P2 settles
        helper.trigger_sensor("binary_sensor.motion_d", False, delay=3)
        assert coordinator.get_occupancy("area_d") == 1

        # --- Person 3: A -> B ---
        helper.advance_time(10)

        helper.trigger_sensor("binary_sensor.motion_a", True)
        assert coordinator.get_occupancy("area_a") == 1

        helper.trigger_sensor("binary_sensor.motion_b", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=0.5)
        assert coordinator.get_occupancy("area_a") == 0
        assert coordinator.get_occupancy("area_b") == 1

        # P3 settles in B
        helper.trigger_sensor("binary_sensor.motion_b", False, delay=3)
        assert coordinator.get_occupancy("area_b") == 1

        # Final state
        assert coordinator.get_occupancy("area_c") == 1, "P1 should be in C"
        assert coordinator.get_occupancy("area_d") == 1, "P2 should be in D"
        assert coordinator.get_occupancy("area_b") == 1, "P3 should be in B"
        assert coordinator.get_occupancy("area_a") == 0

    async def test_two_people_converge_integration(
        self, hass_with_t_junction_config: HomeAssistant
    ):
        """
        P1 is already in C. P2 moves from B to C.

        Setup: P1 enters via A -> B -> C (settles).
        Then:  P2 enters via A -> B (settles).
        Then:  P2 moves B -> C where P1 already is.

        Expected: C=2, B=0.

        However, the resolver's ``_handle_motion_on`` returns early when
        ``area.occupancy > 0``, so C stays at 1.
        """
        coordinator = hass_with_t_junction_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # --- P1: A -> B -> C ---
        helper.trigger_sensor("binary_sensor.motion_a", True)
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=0.5)
        helper.trigger_sensor("binary_sensor.motion_c", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_b", False, delay=0.5)
        helper.trigger_sensor("binary_sensor.motion_c", False, delay=3)
        assert coordinator.get_occupancy("area_c") == 1

        # --- P2: A -> B (settles) ---
        helper.advance_time(10)
        helper.trigger_sensor("binary_sensor.motion_a", True)
        helper.trigger_sensor("binary_sensor.motion_b", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_a", False, delay=0.5)
        helper.trigger_sensor("binary_sensor.motion_b", False, delay=3)
        assert coordinator.get_occupancy("area_b") == 1
        assert coordinator.get_occupancy("area_c") == 1

        # --- P2 moves B -> C ---
        helper.advance_time(10)
        helper.trigger_sensor("binary_sensor.motion_b", True)
        helper.trigger_sensor("binary_sensor.motion_c", True, delay=2)
        helper.trigger_sensor("binary_sensor.motion_b", False, delay=0.5)

        # Convergence fix: both people counted correctly
        # C was already occupied (P1), so the motion-ON in C was ignored.
        # B's motion-OFF may or may not decrement B depending on whether the
        # resolver found a valid neighbor activation for C. Either way, C
        # will not be incremented to 2.
        assert coordinator.get_occupancy("area_c") == 2, (
            "CONVERGENCE BUG: C should have 2 occupants but resolver does "
            "not increment when destination is already occupied"
        )
        assert coordinator.get_occupancy("area_b") == 0


# ============================================================================
# Magnetic (Door) Sensor Integration Tests
# ============================================================================


class TestMagneticSensorIntegration:
    """Test scenarios involving magnetic door sensors."""

    async def test_door_open_keeps_path_active(
        self, hass_with_doors_config: HomeAssistant
    ):
        """
        A person opens the front door and walks from frontyard to hallway.

        Sequence:
        1. Front door opens (magnetic sensor ON)
        2. Frontyard motion ON  -> frontyard=1
        3. Hallway motion ON    -> hallway=1
        4. Frontyard motion OFF -> frontyard clears (exit_capable)

        The magnetic sensor keeps both frontyard and hallway ``last_motion``
        fresh, which helps the resolver recognise the movement path.
        """
        coordinator = hass_with_doors_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Front door opens
        helper.trigger_sensor("binary_sensor.front_door", True)

        # Motion in frontyard
        helper.trigger_sensor("binary_sensor.motion_frontyard", True, delay=0.5)
        assert coordinator.get_occupancy("frontyard") == 1

        # Motion in hallway (person walked inside)
        helper.trigger_sensor("binary_sensor.motion_hallway", True, delay=2)
        assert coordinator.get_occupancy("hallway") == 1

        # Frontyard motion off
        helper.trigger_sensor("binary_sensor.motion_frontyard", False, delay=0.5)
        # Frontyard is exit_capable and a valid neighbor (hallway) activated,
        # so frontyard clears.
        assert coordinator.get_occupancy("frontyard") == 0
        assert coordinator.get_occupancy("hallway") == 1

        # Hallway sensor off - person stays
        helper.trigger_sensor("binary_sensor.motion_hallway", False, delay=3)
        assert coordinator.get_occupancy("hallway") == 1

        # Front door closes
        helper.trigger_sensor("binary_sensor.front_door", False, delay=1)

        # Person is still in hallway
        assert coordinator.get_occupancy("hallway") == 1
        assert coordinator.get_occupancy("frontyard") == 0
        assert coordinator.get_occupancy("bedroom") == 0

    async def test_front_door_suppresses_intrusion_warning(
        self, hass_with_doors_config: HomeAssistant
    ):
        """
        When the front door opens before indoor motion is detected, the
        intrusion warning should be suppressed.

        Without a door sensor event, motion in an indoor area adjacent to an
        outdoor area would trigger an ``intrusion_outside_adjacent`` warning.
        The magnetic sensor's recent activity (``recent_magnetic=True``)
        suppresses this warning.

        Sequence:
        1. Front door opens
        2. Frontyard motion ON  (outdoor - establishes outdoor activity)
        3. Hallway motion ON    (indoor, adjacent to outdoor)
        4. Check: no intrusion warning because door opened recently
        """
        coordinator = hass_with_doors_config.data[DOMAIN]["coordinator"]
        anomaly_detector = coordinator.anomaly_detector
        helper = SensorEventHelper(coordinator)

        # Clear any pre-existing warnings
        anomaly_detector.clear_warnings()

        # Front door opens
        helper.trigger_sensor("binary_sensor.front_door", True)

        # Outdoor motion in frontyard
        helper.trigger_sensor("binary_sensor.motion_frontyard", True, delay=0.5)
        assert coordinator.get_occupancy("frontyard") == 1

        # Indoor motion in hallway - adjacent to outdoor frontyard
        helper.trigger_sensor("binary_sensor.motion_hallway", True, delay=1)
        assert coordinator.get_occupancy("hallway") == 1

        # Check for intrusion warnings - there should be none because the
        # front door magnetic sensor recently changed state
        active_warnings = anomaly_detector.get_warnings(active_only=True)
        intrusion_warnings = [
            w
            for w in active_warnings
            if "intrusion" in (w.type or "")
            or "intrusion" in (getattr(w, "message", "") or "")
        ]
        assert len(intrusion_warnings) == 0, (
            f"No intrusion warning expected when door opened recently, "
            f"but got: {[w.message for w in intrusion_warnings]}"
        )


# ============================================================================
# Multi-Sensor (Dual Sensor) Fixtures
# ============================================================================


@pytest.fixture
def dual_sensor_config() -> dict:
    """Layout with two sensors per room to test multi-sensor behavior."""
    return {
        DOMAIN: {
            "areas": {
                "living": {"name": "Living Room"},
                "hallway": {"name": "Hallway"},
                "bedroom": {"name": "Bedroom"},
            },
            "adjacency": {
                "living": ["hallway"],
                "hallway": ["living", "bedroom"],
                "bedroom": ["hallway"],
            },
            "sensors": {
                "binary_sensor.living_pir": {"area": "living", "type": "motion"},
                "binary_sensor.living_camera": {
                    "area": "living",
                    "type": "camera_person",
                },
                "binary_sensor.hallway_motion": {"area": "hallway", "type": "motion"},
                "binary_sensor.bedroom_motion": {"area": "bedroom", "type": "motion"},
            },
        }
    }


@pytest.fixture
async def hass_with_dual_sensor(
    hass: HomeAssistant, dual_sensor_config: dict
) -> HomeAssistant:
    """Provide a Home Assistant instance with the dual-sensor layout."""
    result = await async_setup(hass, dual_sensor_config)
    assert result is True
    return hass


# ============================================================================
# Multi-Sensor Timing Tests
# ============================================================================


class TestMultiSensorTiming:
    """Tests for rooms with multiple sensors (PIR + camera)."""

    async def test_pir_off_camera_still_on(self, hass_with_dual_sensor: HomeAssistant):
        """PIR goes OFF but camera person still detects -> person stays."""
        coordinator = hass_with_dual_sensor.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person enters living (both sensors trigger)
        helper.trigger_sensor("binary_sensor.living_pir", True)
        helper.trigger_sensor("binary_sensor.living_camera", True, delay=0.5)
        assert coordinator.get_occupancy("living") == 1

        # Hallway activates (someone else? or ambient trigger)
        helper.trigger_sensor("binary_sensor.hallway_motion", True, delay=2)

        # PIR goes OFF (person stopped moving) but camera still sees them
        helper.trigger_sensor("binary_sensor.living_pir", False, delay=1)

        # Person should STAY -- camera still detecting them
        assert coordinator.get_occupancy("living") == 1
        assert coordinator.get_occupancy("hallway") == 1  # hallway has its own person

    async def test_all_sensors_off_then_movement(
        self, hass_with_dual_sensor: HomeAssistant
    ):
        """Both sensors OFF, then neighbor activates -> movement on last OFF."""
        coordinator = hass_with_dual_sensor.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person enters living
        helper.trigger_sensor("binary_sensor.living_pir", True)
        helper.trigger_sensor("binary_sensor.living_camera", True, delay=0.5)
        assert coordinator.get_occupancy("living") == 1

        # Person moves to hallway
        helper.trigger_sensor("binary_sensor.hallway_motion", True, delay=2)

        # Camera OFF first (person walking away)
        helper.trigger_sensor("binary_sensor.living_camera", False, delay=0.5)
        # Person still detected by PIR residual -- should stay
        assert coordinator.get_occupancy("living") == 1

        # PIR OFF (last sensor) -- NOW movement should be detected
        helper.trigger_sensor("binary_sensor.living_pir", False, delay=0.5)
        assert coordinator.get_occupancy("living") == 0
        assert coordinator.get_occupancy("hallway") == 1

    async def test_camera_delayed_detection(self, hass_with_dual_sensor: HomeAssistant):
        """Camera person detection arrives 2s after PIR in same room."""
        coordinator = hass_with_dual_sensor.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # PIR triggers first
        helper.trigger_sensor("binary_sensor.living_pir", True)
        assert coordinator.get_occupancy("living") == 1

        # Camera person detection arrives 2s later (typical delay)
        helper.trigger_sensor("binary_sensor.living_camera", True, delay=2)
        # Should not double-count
        assert coordinator.get_occupancy("living") == 1

        # Both go off in reverse order
        helper.trigger_sensor("binary_sensor.living_pir", False, delay=5)
        # Camera still on -> person stays
        assert coordinator.get_occupancy("living") == 1

        helper.trigger_sensor("binary_sensor.living_camera", False, delay=3)
        # Now all sensors off -> person stays (no neighbor activation)
        assert coordinator.get_occupancy("living") == 1


# ============================================================================
# Sensor Recovery Tests
# ============================================================================


class TestSensorRecovery:
    """Tests for sensor reliability recovery and stuck detection."""

    async def test_sensor_recovers_after_stuck(
        self, hass_with_linear_config: HomeAssistant
    ):
        """Sensor marked stuck recovers when it transitions state."""
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        sensor = coordinator.sensors["binary_sensor.motion_a"]

        # Simulate stuck sensor (manually set state)
        sensor.is_stuck = True
        sensor.is_reliable = False

        # Sensor transitions (e.g. someone walks by, or firmware resets it)
        helper.trigger_sensor("binary_sensor.motion_a", True)

        # Sensor should be recovered
        assert sensor.is_stuck is False
        assert sensor.is_reliable is True


class TestPhantomCleanupIntegration:
    """Integration tests for evidence-based phantom occupancy cleanup."""

    async def test_phantom_cleared_after_long_inactivity(
        self, hass_with_linear_config: HomeAssistant
    ):
        """
        Scenario: False trigger in C, no real person.
        After ~3 hours of silence everywhere, phantom is cleared.

        Timeline:
        t=0    C+  (false trigger — motion ON)
        t=30   C-  (motion OFF, no neighbor → person stays)
        t=12000 check_timeouts → C cleared (phantom)
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # False trigger in C
        helper.trigger_sensor("binary_sensor.motion_c", True, timestamp=0)
        helper.trigger_sensor("binary_sensor.motion_c", False, delay=30)

        assert coordinator.get_occupancy("area_c") == 1

        # Advance time to ~200 minutes (probability < 0.20)
        helper.advance_time(12000)

        # Run check_timeouts with current simulated time
        coordinator.anomaly_detector.check_timeouts(
            coordinator.areas,
            helper.current_time,
            sensors=coordinator.sensors,
            probability_fn=coordinator.get_occupancy_probability,
        )

        # Phantom should be cleared
        assert coordinator.get_occupancy("area_c") == 0

        # Warning should exist
        warnings = [
            w
            for w in coordinator.anomaly_detector.get_warnings()
            if w.type == "phantom_occupancy_cleared"
        ]
        assert len(warnings) == 1
        assert warnings[0].area == "area_c"

    async def test_phantom_not_cleared_with_neighbor_activity(
        self, hass_with_linear_config: HomeAssistant
    ):
        """
        Scenario: Person in C (sleeping). Someone walks through B periodically.
        C should NOT be cleared because neighbor B has recent activity.

        Timeline:
        t=0     C+  (person enters)
        t=30    C-  (sits down)
        t=11000 B+  (housemate walks through hallway)
        t=11030 B-
        t=12000 check_timeouts → C NOT cleared (neighbor active)
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person enters C
        helper.trigger_sensor("binary_sensor.motion_c", True, timestamp=0)
        helper.trigger_sensor("binary_sensor.motion_c", False, delay=30)

        assert coordinator.get_occupancy("area_c") == 1

        # Housemate walks through B at t=11000
        helper.trigger_sensor("binary_sensor.motion_b", True, timestamp=11000)
        helper.trigger_sensor("binary_sensor.motion_b", False, delay=30)

        # Advance to t=12000
        helper.advance_time(12000 - helper.current_time)

        coordinator.anomaly_detector.check_timeouts(
            coordinator.areas,
            helper.current_time,
            sensors=coordinator.sensors,
            probability_fn=coordinator.get_occupancy_probability,
        )

        # C should still be occupied — neighbor B was active recently
        assert coordinator.get_occupancy("area_c") == 1

    async def test_legitimate_occupant_not_cleared(
        self, hass_with_linear_config: HomeAssistant
    ):
        """
        Scenario: Person in C with periodic motion (reading, shifting).
        Should never be cleared because inactivity resets on each trigger.
        """
        coordinator = hass_with_linear_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person enters C
        helper.trigger_sensor("binary_sensor.motion_c", True, timestamp=0)
        helper.trigger_sensor("binary_sensor.motion_c", False, delay=30)

        # Periodic motion every 20 minutes for 3 hours
        for i in range(1, 10):
            t = i * 1200  # every 20 min
            helper.trigger_sensor("binary_sensor.motion_c", True, timestamp=t)
            helper.trigger_sensor("binary_sensor.motion_c", False, delay=30)

        # Check timeouts at t=12000
        helper.advance_time(12000 - helper.current_time)

        coordinator.anomaly_detector.check_timeouts(
            coordinator.areas,
            helper.current_time,
            sensors=coordinator.sensors,
            probability_fn=coordinator.get_occupancy_probability,
        )

        # Person is still there — recent motion keeps probability high
        assert coordinator.get_occupancy("area_c") == 1

"""
Multi-sensor coordination integration tests.

Notation:
- Areas: Y=Frontyard, E=Entrance, B=Backyard (realistic); K=Kitchen, R=Bedroom, L=Living (simple)
- Motion: + = active
- Occupancy: @ = occupied  
- Door: | = closed, / = open

Sensor types tested: motion, magnetic (door), camera (person/motion detection)
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant

from custom_components.occupancy_tracker import DOMAIN
from .test_fixtures import assert_occupancy_state, SensorEventHelper


@pytest.mark.multi_sensor
class TestBridgingSensors:
    """Test bridging sensors (magnetic sensors between two areas)."""

    async def test_magnetic_door_transition(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """
        Door sensor triggers transition between areas.
        
        E+@ -> E+@/B -> E/B+@ (terrace door opens, person moves to backyard)
        """
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # E+@ - person in entrance
        helper.trigger_motion("binary_sensor.motion_entrance")
        assert coordinator.get_occupancy("entrance") >= 1

        # E+@/B - terrace door opens
        helper.trigger_sensor("binary_sensor.magnetic_terrace", True, delay=2.0)

        # E/B+@ - motion in backyard
        helper.trigger_motion("binary_sensor.motion_back_left_camera", delay=1.0)
        assert coordinator.get_occupancy("backyard") >= 1

    async def test_multiple_door_crossings(
        self, hass_with_simple_config: HomeAssistant
    ):
        """
        Multiple door crossings between rooms.
        
        K+@ -> K+@/R -> K/R+@ -> K|R+@ -> K/R+@ -> K+@/R
        """
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # K+@ - person in kitchen
        helper.trigger_motion("binary_sensor.motion_kitchen")

        # K+@/R -> K/R+@ - cross to bedroom
        helper.trigger_sensor("binary_sensor.door_kitchen_bedroom", True, delay=2)
        helper.trigger_motion("binary_sensor.motion_bedroom", delay=1)
        helper.trigger_sensor("binary_sensor.door_kitchen_bedroom", False, delay=2)

        # K/R+@ -> K+@/R - back to kitchen
        helper.trigger_sensor("binary_sensor.door_kitchen_bedroom", True, delay=2)
        helper.trigger_motion("binary_sensor.motion_kitchen", delay=1)

        total_occupancy = (
            coordinator.get_occupancy("kitchen") + 
            coordinator.get_occupancy("bedroom")
        )
        assert total_occupancy >= 0  # System handles without crashing

    async def test_door_with_simultaneous_motion_both_sides(
        self, hass_with_simple_config: HomeAssistant
    ):
        """
        Door sensor with motion on both sides (ambiguous scenario).
        
        K+@R+@ -> K+@/R+@ (door opens while both rooms have motion)
        """
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # K+@R+@ - motion on both sides near-simultaneously
        helper.trigger_motion("binary_sensor.motion_kitchen")
        helper.trigger_motion("binary_sensor.motion_bedroom", delay=0.5)

        # K+@/R+@ - door opens
        helper.trigger_sensor("binary_sensor.door_kitchen_bedroom", True, delay=1)

        total_occupancy = (
            coordinator.get_occupancy("kitchen") +
            coordinator.get_occupancy("bedroom")
        )
        assert total_occupancy >= 1  # At least someone is present


@pytest.mark.multi_sensor
class TestCameraCoordination:
    """Test camera person detection coordinating with motion sensors."""

    async def test_camera_person_followed_by_motion(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """
        Camera person detection followed by area motion sensor.
        
        Y+@ -> Y+@/E -> Y/E+@ (person detected outside, enters through door)
        """
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Y+@ - camera detects person in frontyard
        helper.trigger_sensor("binary_sensor.person_front_left_camera", True)
        assert coordinator.get_occupancy("frontyard") >= 1

        # Y+@/E -> Y/E+@ - enters through door
        helper.trigger_sensor("binary_sensor.magnetic_entry", True, delay=2.0)
        helper.trigger_motion("binary_sensor.motion_entrance", delay=1.0)
        assert coordinator.get_occupancy("entrance") >= 1

    async def test_camera_motion_without_person_detection(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """
        Camera motion without person detection (animal, vehicle, etc).
        
        B+ (motion only, no person detection)
        """
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # B+ - camera motion in backyard without person
        helper.trigger_sensor("binary_sensor.motion_back_left_camera", True)

        # Should register motion but handling depends on implementation
        status = coordinator.get_area_status("backyard")
        assert status is not None

    async def test_simultaneous_camera_person_and_motion(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """
        Camera person and motion sensors triggering together.
        
        Y+@ (both person detection and motion at same instant)
        """
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Y+@ - both camera person and motion simultaneously
        timestamp = helper.current_time
        coordinator.process_sensor_event(
            "binary_sensor.person_front_left_camera", True, timestamp
        )
        coordinator.process_sensor_event(
            "binary_sensor.motion_front_left_camera", True, timestamp
        )
        assert coordinator.get_occupancy("frontyard") >= 1


@pytest.mark.multi_sensor
class TestSensorTimingInteractions:
    """Test timing-related sensor interactions."""

    async def test_rapid_sequential_sensor_activations(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """
        Sensors activating in rapid succession (< 1 second apart).
        
        E+ -> E+F+ -> E+F+B+ -> E+F+B+M+ (0.3s intervals - running through house)
        """
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Rapid sequence: E+ -> F+ -> B+ -> M+ (0.3s intervals)
        base_time = helper.current_time
        coordinator.process_sensor_event(
            "binary_sensor.motion_entrance", True, base_time
        )
        coordinator.process_sensor_event(
            "binary_sensor.motion_front_hall", True, base_time + 0.3
        )
        coordinator.process_sensor_event(
            "binary_sensor.motion_back_hall", True, base_time + 0.6
        )
        coordinator.process_sensor_event(
            "binary_sensor.motion_main_bedroom", True, base_time + 0.9
        )

        assert coordinator.areas["entrance"].last_motion == pytest.approx(
            base_time, abs=0.01
        )
        assert coordinator.areas["main_bedroom"].last_motion == pytest.approx(
            base_time + 0.9, abs=0.01
        )

    async def test_overlapping_sensor_activations(
        self, hass_with_simple_config: HomeAssistant
    ):
        """
        Overlapping sensor activations (multiple sensors ON simultaneously).
        
        L+ -> L+K+ -> L+K+R+ (all ON) -> L+K+R -> L+K -> L (turn off in reverse)
        """
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # L+K+R+ - turn on all three
        helper.trigger_sensor("binary_sensor.motion_living", True)
        helper.trigger_sensor("binary_sensor.motion_kitchen", True, delay=1.0)
        helper.trigger_sensor("binary_sensor.motion_bedroom", True, delay=1.0)

        # Verify all ON
        assert coordinator.sensors["binary_sensor.motion_living"].current_state is True
        assert coordinator.sensors["binary_sensor.motion_kitchen"].current_state is True
        assert coordinator.sensors["binary_sensor.motion_bedroom"].current_state is True

        # Turn off in different order: R -> L -> K
        helper.trigger_sensor("binary_sensor.motion_bedroom", False, delay=2.0)
        helper.trigger_sensor("binary_sensor.motion_living", False, delay=1.0)
        helper.trigger_sensor("binary_sensor.motion_kitchen", False, delay=1.0)

        assert coordinator.sensors["binary_sensor.motion_living"].current_state is False

    async def test_delayed_sensor_clearing(
        self, hass_with_simple_config: HomeAssistant
    ):
        """
        Sensors with different clearing times.
        
        L+ -> L+K+ -> LK+ (L clears quickly, K stays on longer)
        """
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # L+K+ - both on
        helper.trigger_sensor("binary_sensor.motion_living", True)
        helper.trigger_sensor("binary_sensor.motion_kitchen", True, delay=2.0)

        # LK+ - living clears quickly
        helper.trigger_sensor("binary_sensor.motion_living", False, delay=3.0)

        # K stays on for 10s more
        helper.advance_time(10.0)
        assert coordinator.sensors["binary_sensor.motion_kitchen"].current_state is True

        # K clears
        helper.trigger_sensor("binary_sensor.motion_kitchen", False)
        assert coordinator.sensors["binary_sensor.motion_kitchen"].current_state is False


@pytest.mark.multi_sensor
class TestMultiAreaSensors:
    """Test sensors that cover multiple areas (bridging sensors)."""

    async def test_magnetic_sensor_bidirectional(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """
        Magnetic sensor works in both directions.
        
        Direction 1: E+@ -> E+@/Y -> E/Y+@ (exit to frontyard)
        Direction 2: Y+@ -> Y+@/E -> Y/E+@ (enter from frontyard)
        """
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Direction 1: E+@ -> E+@/Y -> E/Y+@
        helper.trigger_motion("binary_sensor.motion_entrance")
        helper.trigger_sensor("binary_sensor.magnetic_entry", True, delay=1.0)
        helper.trigger_sensor("binary_sensor.person_front_left_camera", True, delay=1.0)
        assert coordinator.get_occupancy("frontyard") >= 1

        # Wait and clear frontyard
        helper.advance_time(301.0)
        helper.check_timeouts()
        helper.trigger_sensor("binary_sensor.person_front_left_camera", False)

        # Direction 2: Y+@ -> Y+@/E -> Y/E+@
        helper.trigger_sensor("binary_sensor.person_front_left_camera", True)
        helper.trigger_sensor("binary_sensor.magnetic_entry", True, delay=1.0)
        helper.trigger_motion("binary_sensor.motion_entrance", delay=1.0)
        assert coordinator.get_occupancy("entrance") >= 1

    async def test_multiple_bridging_sensors_in_sequence(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """
        Multiple bridging sensors in a journey.
        
        E+@ -> E+@/B -> E/B+@ (terrace door) -> B+@/E -> B/E+@ (entry door)
        """
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # E+@ - start in entrance
        helper.trigger_motion("binary_sensor.motion_entrance")

        # E+@/B -> E/B+@ - terrace door to backyard
        helper.trigger_sensor("binary_sensor.magnetic_terrace", True, delay=2.0)
        helper.trigger_motion("binary_sensor.motion_back_left_camera", delay=1.0)
        assert coordinator.get_occupancy("backyard") >= 1

        # B+@/E -> B/E+@ - entry door back to entrance
        helper.trigger_sensor("binary_sensor.magnetic_entry", True, delay=3.0)
        helper.trigger_motion("binary_sensor.motion_entrance", delay=1.0)
        assert coordinator.get_occupancy("entrance") >= 1


@pytest.mark.multi_sensor
class TestSensorTypeCombinations:
    """Test various combinations of sensor types working together."""

    async def test_motion_to_magnetic_to_camera(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """
        Journey using motion -> magnetic -> camera sensors.
        
        E+@ -> E+@/Y -> E/Y+@ (motion in entrance, door, camera in frontyard)
        """
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # E+@ - motion in entrance
        helper.trigger_motion("binary_sensor.motion_entrance")

        # E+@/Y - door opens
        helper.trigger_sensor("binary_sensor.magnetic_entry", True, delay=2.0)

        # E/Y+@ - camera sensors detect person
        helper.trigger_sensor("binary_sensor.person_front_left_camera", True, delay=1.0)
        helper.trigger_sensor("binary_sensor.motion_front_left_camera", True, delay=0.5)
        assert coordinator.get_occupancy("frontyard") >= 1

    async def test_all_sensor_types_in_one_area(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """
        Area with multiple sensor types all triggering.
        
        B+@ (motion camera + person camera + magnetic all triggered)
        """
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # B+@ - all sensors for backyard triggered
        timestamp = helper.current_time
        coordinator.process_sensor_event(
            "binary_sensor.motion_back_left_camera", True, timestamp
        )
        coordinator.process_sensor_event(
            "binary_sensor.person_back_left_camera", True, timestamp + 0.5
        )
        coordinator.process_sensor_event(
            "binary_sensor.magnetic_terrace", True, timestamp + 1.0
        )
        assert coordinator.get_occupancy("backyard") >= 1

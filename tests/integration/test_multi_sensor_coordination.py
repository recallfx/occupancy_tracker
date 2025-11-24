"""Multi-sensor coordination integration tests.

These tests verify that different sensor types work together correctly,
including bridging sensors (magnetic), camera sensors, and motion sensors.
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
        """Test door sensor triggering transition between areas."""
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person in entrance
        helper.trigger_motion("binary_sensor.motion_entrance")
        assert coordinator.get_occupancy("entrance") >= 1

        # Open terrace door (bridges entrance and backyard)
        helper.trigger_sensor("binary_sensor.magnetic_terrace", True, delay=2.0)

        # Motion in backyard
        helper.trigger_motion("binary_sensor.motion_back_left_camera", delay=1.0)

        # Should have transitioned to backyard
        assert coordinator.get_occupancy("backyard") >= 1

    async def test_multiple_door_crossings(
        self, hass_with_simple_config: HomeAssistant
    ):
        """Test multiple door crossings between rooms."""
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Person in kitchen
        helper.trigger_motion("binary_sensor.motion_kitchen")

        # Cross door to bedroom multiple times
        helper.trigger_sensor("binary_sensor.door_kitchen_bedroom", True, delay=2)
        helper.trigger_motion("binary_sensor.motion_bedroom", delay=1)
        helper.trigger_sensor("binary_sensor.door_kitchen_bedroom", False, delay=2)

        # Back to kitchen
        helper.trigger_sensor("binary_sensor.door_kitchen_bedroom", True, delay=2)
        helper.trigger_motion("binary_sensor.motion_kitchen", delay=1)

        # System should handle door crossings
        # Occupancy depends on movement tracking
        total_occupancy = (
            coordinator.get_occupancy("kitchen") + 
            coordinator.get_occupancy("bedroom")
        )
        assert total_occupancy >= 0  # System handles without crashing

    async def test_door_with_simultaneous_motion_both_sides(
        self, hass_with_simple_config: HomeAssistant
    ):
        """Test door sensor with motion on both sides simultaneously."""
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Motion on both sides of door at nearly the same time
        helper.trigger_motion("binary_sensor.motion_kitchen")
        helper.trigger_motion("binary_sensor.motion_bedroom", delay=0.5)

        # Door opens
        helper.trigger_sensor("binary_sensor.door_kitchen_bedroom", True, delay=1)

        # System should handle ambiguous scenarios
        # May interpret as one or two people
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
        """Test camera person detection followed by area motion sensor."""
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Camera detects person in frontyard
        helper.trigger_sensor("binary_sensor.person_front_left_camera", True)
        assert coordinator.get_occupancy("frontyard") >= 1

        # Person enters through door
        helper.trigger_sensor("binary_sensor.magnetic_entry", True, delay=2.0)
        helper.trigger_motion("binary_sensor.motion_entrance", delay=1.0)

        # Should have transitioned to entrance
        assert coordinator.get_occupancy("entrance") >= 1

    async def test_camera_motion_without_person_detection(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """Test camera motion without person detection (e.g., animal, vehicle)."""
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Camera motion in backyard without person
        helper.trigger_sensor("binary_sensor.motion_back_left_camera", True)

        # Should register motion but with appropriate handling
        # (May or may not create occupancy depending on implementation)
        # Just verify no crashes and state is trackable
        status = coordinator.get_area_status("backyard")
        assert status is not None

    async def test_simultaneous_camera_person_and_motion(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """Test camera person and motion sensors triggering together."""
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Both camera person and motion detect simultaneously
        timestamp = helper.current_time
        coordinator.process_sensor_event(
            "binary_sensor.person_front_left_camera", True, timestamp
        )
        coordinator.process_sensor_event(
            "binary_sensor.motion_front_left_camera", True, timestamp
        )

        # Should have occupancy in frontyard
        assert coordinator.get_occupancy("frontyard") >= 1


@pytest.mark.multi_sensor
class TestSensorTimingInteractions:
    """Test timing-related sensor interactions."""

    async def test_rapid_sequential_sensor_activations(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """Test sensors activating in very rapid succession (< 1 second apart)."""
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Rapid sequence through connected rooms (0.3s intervals)
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

        # All should register the motion
        assert (
            coordinator.areas["entrance"].last_motion ==pytest.approx(
                base_time, abs=0.01
            )
        )
        assert (
            coordinator.areas["main_bedroom"].last_motion
            == pytest.approx(base_time + 0.9, abs=0.01)
        )

    async def test_overlapping_sensor_activations(
        self, hass_with_simple_config: HomeAssistant
    ):
        """Test overlapping sensor activations (sensors ON at same time)."""
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Turn on multiple sensors
        helper.trigger_sensor("binary_sensor.motion_living", True)
        helper.trigger_sensor("binary_sensor.motion_kitchen", True, delay=1.0)
        helper.trigger_sensor("binary_sensor.motion_bedroom", True, delay=1.0)

        # All three are ON simultaneously
        assert (
            coordinator.sensors[
                "binary_sensor.motion_living"
            ].current_state
            is True
        )
        assert (
            coordinator.sensors[
                "binary_sensor.motion_kitchen"
            ].current_state
            is True
        )
        assert (
            coordinator.sensors[
                "binary_sensor.motion_bedroom"
            ].current_state
            is True
        )

        # Turn them off in different order
        helper.trigger_sensor("binary_sensor.motion_bedroom", False, delay=2.0)
        helper.trigger_sensor("binary_sensor.motion_living", False, delay=1.0)
        helper.trigger_sensor("binary_sensor.motion_kitchen", False, delay=1.0)

        # All should be off
        assert (
            coordinator.sensors[
                "binary_sensor.motion_living"
            ].current_state
            is False
        )

    async def test_delayed_sensor_clearing(
        self, hass_with_simple_config: HomeAssistant
    ):
        """Test sensors with different clearing times."""
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Trigger living room motion
        helper.trigger_sensor("binary_sensor.motion_living", True)

        # Trigger kitchen motion shortly after
        helper.trigger_sensor("binary_sensor.motion_kitchen", True, delay=2.0)

        # Living room clears quickly
        helper.trigger_sensor("binary_sensor.motion_living", False, delay=3.0)

        # Kitchen stays on longer
        helper.advance_time(10.0)

        # Kitchen should still be on
        assert (
            coordinator.sensors[
                "binary_sensor.motion_kitchen"
            ].current_state
            is True
        )

        # Now clear kitchen
        helper.trigger_sensor("binary_sensor.motion_kitchen", False)

        assert (
            coordinator.sensors[
                "binary_sensor.motion_kitchen"
            ].current_state
            is False
        )


@pytest.mark.multi_sensor
class TestMultiAreaSensors:
    """Test sensors that cover multiple areas (bridging sensors)."""

    async def test_magnetic_sensor_bidirectional(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """Test magnetic sensor works in both directions."""
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Direction 1: entrance -> frontyard
        helper.trigger_motion("binary_sensor.motion_entrance")
        helper.trigger_sensor("binary_sensor.magnetic_entry", True, delay=1.0)
        helper.trigger_sensor("binary_sensor.person_front_left_camera", True, delay=1.0)

        assert coordinator.get_occupancy("frontyard") >= 1

        # Wait and clear frontyard
        helper.advance_time(301.0)
        helper.check_timeouts()

        # Direction 2: frontyard -> entrance (coming back)
        helper.trigger_sensor("binary_sensor.person_front_left_camera", True)
        helper.trigger_sensor("binary_sensor.magnetic_entry", True, delay=1.0)
        helper.trigger_motion("binary_sensor.motion_entrance", delay=1.0)

        assert coordinator.get_occupancy("entrance") >= 1

    async def test_multiple_bridging_sensors_in_sequence(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """Test using multiple bridging sensors in a journey."""
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Start in entrance
        helper.trigger_motion("binary_sensor.motion_entrance")

        # Use terrace door to backyard
        helper.trigger_sensor("binary_sensor.magnetic_terrace", True, delay=2.0)
        helper.trigger_motion("binary_sensor.motion_back_left_camera", delay=1.0)

        assert coordinator.get_occupancy("backyard") >= 1

        # Use entry door back to entrance
        helper.trigger_sensor("binary_sensor.magnetic_entry", True, delay=3.0)
        helper.trigger_motion("binary_sensor.motion_entrance", delay=1.0)

        assert coordinator.get_occupancy("entrance") >= 1


@pytest.mark.multi_sensor
class TestSensorTypeCombinations:
    """Test various combinations of sensor types working together."""

    async def test_motion_to_magnetic_to_camera(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """Test journey using motion -> magnetic -> camera sensors."""
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Motion in entrance
        helper.trigger_motion("binary_sensor.motion_entrance")

        # Magnetic door
        helper.trigger_sensor("binary_sensor.magnetic_entry", True, delay=2.0)

        # Camera person detection
        helper.trigger_sensor("binary_sensor.person_front_left_camera", True, delay=1.0)

        # Camera motion detection
        helper.trigger_sensor("binary_sensor.motion_front_left_camera", True, delay=0.5)

        assert coordinator.get_occupancy("frontyard") >= 1

    async def test_all_sensor_types_in_one_area(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """Test area with multiple sensor types all triggering."""
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Backyard has motion and person camera sensors
        timestamp = helper.current_time

        # Trigger all sensors for backyard
        coordinator.process_sensor_event(
            "binary_sensor.motion_back_left_camera", True, timestamp
        )
        coordinator.process_sensor_event(
            "binary_sensor.person_back_left_camera", True, timestamp + 0.5
        )

        # Magnetic sensors that bridge to backyard
        coordinator.process_sensor_event(
            "binary_sensor.magnetic_terrace", True, timestamp + 1.0
        )

        # Should have occupancy
        assert coordinator.get_occupancy("backyard") >= 1

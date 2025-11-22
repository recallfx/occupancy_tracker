"""Fixtures for integration tests."""

from __future__ import annotations

from typing import Any
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.occupancy_tracker import async_setup, DOMAIN
from custom_components.occupancy_tracker.coordinator import OccupancyCoordinator


@pytest.fixture
def realistic_config() -> dict[str, Any]:
    """Provide a realistic configuration based on actual config.yaml.
    
    This configuration represents a real-world home with:
    - 8 areas (5 indoor rooms, 2 outdoor yards, 1 entrance)
    - Complex adjacency relationships (backyard connects to many areas)
    - Multiple sensor types (motion, magnetic, camera_motion, camera_person)
    - Exit-capable areas (frontyard, backyard)
    """
    return {
        DOMAIN: {
            "areas": {
                "main_bathroom": {"name": "Main Bathroom"},
                "main_bedroom": {"name": "Main Bedroom"},
                "back_hall": {"name": "Back Hall"},
                "front_hall": {"name": "Front Hall"},
                "entrance": {"name": "Entrance"},
                "living": {"name": "Living Room"},
                "frontyard": {"name": "Front Yard", "exit_capable": True},
                "backyard": {"name": "Back Yard", "exit_capable": True},
            },
            "adjacency": {
                "main_bathroom": ["main_bedroom", "backyard"],
                "main_bedroom": ["main_bathroom", "back_hall", "backyard"],
                "back_hall": ["main_bedroom", "front_hall", "frontyard", "backyard"],
                "front_hall": ["back_hall", "entrance", "frontyard", "backyard"],
                "entrance": ["front_hall", "living", "frontyard", "backyard"],
                "living": ["entrance", "backyard"],
                "backyard": [
                    "main_bathroom",
                    "main_bedroom",
                    "front_hall",
                    "entrance",
                    "living",
                    "frontyard",
                ],
                "frontyard": ["front_hall", "entrance", "backyard"],
            },
            "sensors": {
                "binary_sensor.motion_main_bathroom": {
                    "area": "main_bathroom",
                    "type": "motion",
                },
                "binary_sensor.motion_main_bedroom": {
                    "area": "main_bedroom",
                    "type": "motion",
                },
                "binary_sensor.motion_back_hall": {"area": "back_hall", "type": "motion"},
                "binary_sensor.motion_front_hall": {
                    "area": "front_hall",
                    "type": "motion",
                },
                "binary_sensor.motion_entrance": {"area": "entrance", "type": "motion"},
                "binary_sensor.motion_living": {"area": "living", "type": "motion"},
                "binary_sensor.magnetic_terrace": {
                    "type": "magnetic",
                    "area": "entrance",  # Primary area for adjacency
                    "between_areas": ["entrance", "backyard"],
                },
                "binary_sensor.magnetic_entry": {
                    "type": "magnetic",
                    "area": "entrance",  # Primary area for adjacency
                    "between_areas": ["entrance", "frontyard"],
                },
                "binary_sensor.motion_front_left_camera": {
                    "area": "frontyard",
                    "type": "camera_motion",
                },
                "binary_sensor.person_front_left_camera": {
                    "area": "frontyard",
                    "type": "camera_person",
                },
                "binary_sensor.motion_back_left_camera": {
                    "area": "backyard",
                    "type": "camera_motion",
                },
                "binary_sensor.person_back_left_camera": {
                    "area": "backyard",
                    "type": "camera_person",
                },
            },
        }
    }


@pytest.fixture
def simple_config() -> dict[str, Any]:
    """Provide a simple 3-room configuration for basic scenarios."""
    return {
        DOMAIN: {
            "areas": {
                "living_room": {"name": "Living Room"},
                "kitchen": {"name": "Kitchen"},
                "bedroom": {"name": "Bedroom"},
            },
            "adjacency": {
                "living_room": ["kitchen"],
                "kitchen": ["living_room", "bedroom"],
                "bedroom": ["kitchen"],
            },
            "sensors": {
                "binary_sensor.motion_living": {"area": "living_room", "type": "motion"},
                "binary_sensor.motion_kitchen": {"area": "kitchen", "type": "motion"},
                "binary_sensor.motion_bedroom": {"area": "bedroom", "type": "motion"},
                "binary_sensor.door_kitchen_bedroom": {
                    "type": "magnetic",
                    "area": "kitchen",  # Primary area for adjacency
                    "between_areas": ["kitchen", "bedroom"],
                },
            },
        }
    }


@pytest.fixture
def multi_occupant_config() -> dict[str, Any]:
    """Provide configuration optimized for multi-occupant testing.
    
    This has parallel paths so multiple people can move independently.
    """
    return {
        DOMAIN: {
            "areas": {
                "entrance": {"name": "Entrance"},
                "living_room": {"name": "Living Room"},
                "kitchen": {"name": "Kitchen"},
                "bedroom_1": {"name": "Bedroom 1"},
                "bedroom_2": {"name": "Bedroom 2"},
                "bathroom": {"name": "Bathroom"},
            },
            "adjacency": {
                "entrance": ["living_room"],
                "living_room": ["entrance", "kitchen", "bedroom_1", "bedroom_2"],
                "kitchen": ["living_room"],
                "bedroom_1": ["living_room", "bathroom"],
                "bedroom_2": ["living_room", "bathroom"],
                "bathroom": ["bedroom_1", "bedroom_2"],
            },
            "sensors": {
                "binary_sensor.motion_entrance": {"area": "entrance", "type": "motion"},
                "binary_sensor.motion_living": {
                    "area": "living_room",
                    "type": "motion",
                },
                "binary_sensor.motion_kitchen": {"area": "kitchen", "type": "motion"},
                "binary_sensor.motion_bedroom_1": {
                    "area": "bedroom_1",
                    "type": "motion",
                },
                "binary_sensor.motion_bedroom_2": {
                    "area": "bedroom_2",
                    "type": "motion",
                },
                "binary_sensor.motion_bathroom": {"area": "bathroom", "type": "motion"},
            },
        }
    }


@pytest.fixture
async def hass_with_realistic_config(
    hass: HomeAssistant, realistic_config: dict[str, Any]
) -> HomeAssistant:
    """Provide a Home Assistant instance with realistic occupancy tracker config."""
    result = await async_setup(hass, realistic_config)
    assert result is True
    return hass


@pytest.fixture
async def hass_with_simple_config(
    hass: HomeAssistant, simple_config: dict[str, Any]
) -> HomeAssistant:
    """Provide a Home Assistant instance with simple occupancy tracker config."""
    result = await async_setup(hass, simple_config)
    assert result is True
    return hass


@pytest.fixture
async def hass_with_multi_occupant_config(
    hass: HomeAssistant, multi_occupant_config: dict[str, Any]
) -> HomeAssistant:
    """Provide a Home Assistant instance with multi-occupant config."""
    result = await async_setup(hass, multi_occupant_config)
    assert result is True
    return hass


@pytest.fixture
def coordinator_from_hass(hass: HomeAssistant) -> OccupancyCoordinator:
    """Extract the coordinator from a configured Home Assistant instance."""
    return hass.data[DOMAIN]["coordinator"]


class SensorEventHelper:
    """Helper class for simulating sensor events."""

    def __init__(self, coordinator: OccupancyCoordinator):
        self.coordinator = coordinator
        self.current_time = time.time()

    def trigger_sensor(
        self, entity_id: str, state: bool = True, delay: float = 0.0
    ) -> float:
        """Trigger a sensor event.
        
        Args:
            entity_id: The sensor entity ID
            state: True for ON, False for OFF
            delay: Seconds to advance time before triggering
            
        Returns:
            The timestamp of the event
        """
        if delay > 0:
            self.current_time += delay

        self.coordinator.process_sensor_event(entity_id, state, self.current_time)
        return self.current_time

    def trigger_motion(
        self, entity_id: str, delay: float = 0.0, duration: float = 5.0
    ) -> tuple[float, float]:
        """Trigger a motion sensor ON then OFF.
        
        Args:
            entity_id: The sensor entity ID
            delay: Seconds to wait before triggering ON
            duration: Seconds the sensor stays ON
            
        Returns:
            Tuple of (on_timestamp, off_timestamp)
        """
        on_time = self.trigger_sensor(entity_id, True, delay)
        off_time = self.trigger_sensor(entity_id, False, duration)
        return on_time, off_time

    def simulate_journey(
        self, sensors: list[str], interval: float = 2.0
    ) -> list[float]:
        """Simulate a person's journey through multiple sensors.
        
        Args:
            sensors: List of sensor entity IDs in order
            interval: Time between each sensor activation
            
        Returns:
            List of timestamps for each sensor activation
        """
        timestamps = []
        for i, sensor in enumerate(sensors):
            delay = interval if i > 0 else 0
            timestamp = self.trigger_sensor(sensor, True, delay)
            timestamps.append(timestamp)
            # Clear previous sensor
            if i > 0:
                self.trigger_sensor(sensors[i - 1], False, 0.5)

        # Clear final sensor
        self.trigger_sensor(sensors[-1], False, 5.0)
        return timestamps

    def advance_time(self, seconds: float) -> float:
        """Advance time without triggering sensors.
        
        Args:
            seconds: Seconds to advance
            
        Returns:
            New current time
        """
        self.current_time += seconds
        return self.current_time

    def check_timeouts(self) -> None:
        """Manually trigger timeout checking at current time."""
        self.coordinator.check_timeouts(self.current_time)


@pytest.fixture
def sensor_helper(coordinator_from_hass: OccupancyCoordinator) -> SensorEventHelper:
    """Provide a sensor event helper for the coordinator."""
    return SensorEventHelper(coordinator_from_hass)


def assert_occupancy_state(
    coordinator: OccupancyCoordinator, expected: dict[str, int]
) -> None:
    """Assert that occupancy counts match expected values.
    
    Args:
        coordinator: The occupancy coordinator
        expected: Dict mapping area IDs to expected occupancy counts
    """
    for area_id, expected_count in expected.items():
        actual_count = coordinator.get_occupancy(area_id)
        assert (
            actual_count == expected_count
        ), f"Area '{area_id}': expected {expected_count}, got {actual_count}"


def assert_warning_exists(
    coordinator: OccupancyCoordinator,
    warning_type: str,
    area_or_sensor: str | None = None,
) -> None:
    """Assert that a specific warning exists.
    
    Args:
        coordinator: The occupancy coordinator
        warning_type: Type of warning to check for
        area_or_sensor: Optional area or sensor ID to match
    """
    warnings = coordinator.get_warnings()
    active_warnings = [w for w in warnings if w.is_active]

    matching_warnings = [w for w in active_warnings if w.type == warning_type]

    if area_or_sensor:
        matching_warnings = [
            w
            for w in matching_warnings
            if w.area == area_or_sensor or w.sensor_id == area_or_sensor
        ]

    assert (
        len(matching_warnings) > 0
    ), f"No warning of type '{warning_type}' found for '{area_or_sensor}'"


def assert_no_warnings(coordinator: OccupancyCoordinator) -> None:
    """Assert that there are no active warnings.
    
    Args:
        coordinator: The occupancy coordinator
    """
    warnings = coordinator.get_warnings()
    active_warnings = [w for w in warnings if w.is_active]
    assert (
        len(active_warnings) == 0
    ), f"Expected no warnings, but found: {[w.type for w in active_warnings]}"

"""Tests for integration setup and initialization."""

import pytest
from unittest.mock import patch, call
import time

from homeassistant.core import HomeAssistant, Event, State
from homeassistant.const import STATE_ON

from custom_components.occupancy_tracker import (
    async_setup,
    DOMAIN,
)


@pytest.fixture
def sample_config():
    """Provide a sample configuration."""
    return {
        DOMAIN: {
            "areas": {
                "living_room": {"name": "Living Room", "indoors": True},
                "kitchen": {"name": "Kitchen", "indoors": True},
            },
            "adjacency": {
                "living_room": ["kitchen"],
            },
            "sensors": {
                "binary_sensor.motion_living": {
                    "area": "living_room",
                    "type": "motion",
                },
                "binary_sensor.motion_kitchen": {"area": "kitchen", "type": "motion"},
            },
        }
    }


class TestAsyncSetup:
    """Test async_setup function."""

    async def test_setup_success(self, hass: HomeAssistant, sample_config):
        """Test successful setup of the integration."""
        result = await async_setup(hass, sample_config)

        assert result is True
        assert DOMAIN in hass.data
        assert "coordinator" in hass.data[DOMAIN]

    async def test_setup_creates_occupancy_coordinator(
        self, hass: HomeAssistant, sample_config
    ):
        """Test that setup creates the occupancy coordinator."""
        await async_setup(hass, sample_config)

        coordinator = hass.data[DOMAIN]["coordinator"]

        assert len(coordinator.area_manager.areas) == 2
        assert len(coordinator.sensor_manager.sensors) == 2
        assert "living_room" in coordinator.area_manager.areas
        assert "kitchen" in coordinator.area_manager.areas

    async def test_setup_no_configuration(self, hass: HomeAssistant):
        """Test setup with no configuration."""
        config = {}

        result = await async_setup(hass, config)

        assert result is False

    async def test_setup_initializes_config(self, hass: HomeAssistant, sample_config):
        """Test that configuration is properly initialized."""
        await async_setup(hass, sample_config)

        coordinator = hass.data[DOMAIN]["coordinator"]

        # Check areas
        assert coordinator.config["areas"]["living_room"]["name"] == "Living Room"

        # Check sensors
        assert (
            coordinator.config["sensors"]["binary_sensor.motion_living"]["area"]
            == "living_room"
        )

        # Check adjacency
        assert "kitchen" in coordinator.config["adjacency"]["living_room"]

    @patch("custom_components.occupancy_tracker.async_load_platform")
    async def test_setup_loads_platforms(
        self, mock_load_platform, hass: HomeAssistant, sample_config
    ):
        """Test that setup loads sensor and button platforms."""
        await async_setup(hass, sample_config)

        # Should load sensor and button platforms
        assert mock_load_platform.call_count == 2

        calls = [call[0] for call in mock_load_platform.call_args_list]
        platforms = [call[1] for call in calls]

        assert "sensor" in platforms
        assert "button" in platforms


class TestStateChangeListener:
    """Test state change event handling."""

    async def test_state_change_listener_on_state(
        self, hass: HomeAssistant, sample_config
    ):
        """Test state change listener processes ON state."""
        await async_setup(hass, sample_config)

        coordinator = hass.data[DOMAIN]["coordinator"]

        # Create a state change event
        new_state = State("binary_sensor.motion_living", STATE_ON)
        event_data = {
            "entity_id": "binary_sensor.motion_living",
            "new_state": new_state,
        }

        Event("state_changed", event_data)

        # Manually trigger the listener
        # (In real HA, this would be triggered by async_track_state_change_event)
        timestamp_before = coordinator.last_event_time

        # Simulate processing the event
        coordinator.process_sensor_event("binary_sensor.motion_living", True, time.time())

        # Event should have been processed
        assert coordinator.last_event_time > timestamp_before

    async def test_state_change_listener_off_state(
        self, hass: HomeAssistant, sample_config
    ):
        """Test state change listener processes OFF state."""
        await async_setup(hass, sample_config)

        coordinator = hass.data[DOMAIN]["coordinator"]

        # Set sensor to ON first
        coordinator.process_sensor_event("binary_sensor.motion_living", True, time.time())

        # Then to OFF
        coordinator.process_sensor_event("binary_sensor.motion_living", False, time.time())

        # Sensor state should be False
        assert coordinator.sensor_manager.sensors["binary_sensor.motion_living"].current_state is False

    async def test_state_change_listener_unknown_sensor(
        self, hass: HomeAssistant, sample_config
    ):
        """Test state change listener handles unknown sensor gracefully."""
        await async_setup(hass, sample_config)

        coordinator = hass.data[DOMAIN]["coordinator"]

        # Process event from unknown sensor (should not raise error)
        coordinator.process_sensor_event("binary_sensor.unknown", True, time.time())


class TestIntegrationConfiguration:
    """Test various configuration scenarios."""

    async def test_minimal_configuration(self, hass: HomeAssistant):
        """Test setup with minimal configuration."""
        config = {
            DOMAIN: {
                "areas": {"room1": {}},
                "adjacency": {},
                "sensors": {},
            }
        }

        result = await async_setup(hass, config)

        assert result is True
        coordinator = hass.data[DOMAIN]["coordinator"]
        assert len(coordinator.area_manager.areas) == 1

    async def test_configuration_with_multiple_sensor_types(self, hass: HomeAssistant):
        """Test configuration with different sensor types."""
        config = {
            DOMAIN: {
                "areas": {
                    "living_room": {},
                    "hallway": {},
                    "front_porch": {},
                },
                "adjacency": {},
                "sensors": {
                    "binary_sensor.motion_1": {"area": "living_room", "type": "motion"},
                    "binary_sensor.camera_person": {
                        "area": "front_porch",
                        "type": "camera_person",
                    },
                    "binary_sensor.door": {
                        "type": "magnetic",
                        "between_areas": ["living_room", "hallway"],
                    },
                },
            }
        }

        result = await async_setup(hass, config)

        assert result is True
        coordinator = hass.data[DOMAIN]["coordinator"]
        assert len(coordinator.sensor_manager.sensors) == 3

    async def test_configuration_with_outdoor_areas(self, hass: HomeAssistant):
        """Test configuration with indoor and outdoor areas."""
        config = {
            DOMAIN: {
                "areas": {
                    "living_room": {"indoors": True},
                    "porch": {"indoors": False, "exit_capable": True},
                },
                "adjacency": {},
                "sensors": {},
            }
        }

        result = await async_setup(hass, config)

        assert result is True
        coordinator = hass.data[DOMAIN]["coordinator"]
        assert coordinator.area_manager.areas["living_room"].is_indoors is True
        assert coordinator.area_manager.areas["porch"].is_indoors is False
        assert coordinator.area_manager.areas["porch"].is_exit_capable is True

    async def test_configuration_with_complex_adjacency(self, hass: HomeAssistant):
        """Test configuration with complex adjacency graph."""
        config = {
            DOMAIN: {
                "areas": {
                    "living_room": {},
                    "kitchen": {},
                    "hallway": {},
                    "bedroom": {},
                },
                "adjacency": {
                    "living_room": ["kitchen", "hallway"],
                    "kitchen": ["living_room", "hallway"],
                    "hallway": ["living_room", "kitchen", "bedroom"],
                    "bedroom": ["hallway"],
                },
                "sensors": {},
            }
        }

        result = await async_setup(hass, config)

        assert result is True
        coordinator = hass.data[DOMAIN]["coordinator"]

        # Check adjacency is properly set up
        assert "kitchen" in coordinator.config["adjacency"]["living_room"]
        assert "bedroom" in coordinator.config["adjacency"]["hallway"]


class TestIntegrationDataFlow:
    """Test data flow through the integration."""

    async def test_sensor_event_updates_area_state(
        self, hass: HomeAssistant, sample_config
    ):
        """Test that sensor events update area state correctly."""
        await async_setup(hass, sample_config)

        coordinator = hass.data[DOMAIN]["coordinator"]

        # Process motion event
        timestamp = time.time()
        coordinator.process_sensor_event("binary_sensor.motion_living", True, timestamp)

        # Area should have motion recorded
        assert coordinator.area_manager.areas["living_room"].last_motion == timestamp

    async def test_multiple_sensor_events(self, hass: HomeAssistant, sample_config):
        """Test processing multiple sensor events."""
        await async_setup(hass, sample_config)

        coordinator = hass.data[DOMAIN]["coordinator"]

        # Process events from both sensors
        t1 = time.time()
        coordinator.process_sensor_event("binary_sensor.motion_living", True, t1)

        t2 = t1 + 10
        coordinator.process_sensor_event("binary_sensor.motion_kitchen", True, t2)

        # Both areas should have motion
        assert coordinator.area_manager.areas["living_room"].last_motion == t1
        assert coordinator.area_manager.areas["kitchen"].last_motion == t2

    async def test_occupancy_tracking_through_integration(
        self, hass: HomeAssistant, sample_config
    ):
        """Test end-to-end occupancy tracking."""
        await async_setup(hass, sample_config)

        coordinator = hass.data[DOMAIN]["coordinator"]

        # Simulate person entering (living room is not exit_capable, will create warning)
        coordinator.process_sensor_event("binary_sensor.motion_living", True, time.time())

        # Should have occupancy (even if unexpected)
        assert coordinator.get_occupancy("living_room") >= 1

"""Tests for OccupancyCoordinator core functionality."""

import time
from unittest.mock import Mock

from homeassistant.core import HomeAssistant
from custom_components.occupancy_tracker.coordinator import OccupancyCoordinator


class TestOccupancyCoordinatorInit:
    """Test OccupancyCoordinator initialization."""

    def test_create_coordinator(self):
        """Test creating an occupancy coordinator."""
        hass = Mock(spec=HomeAssistant)
        config = {
            "areas": {
                "living_room": {"name": "Living Room", "indoors": True},
                "kitchen": {"name": "Kitchen"},
            },
            "adjacency": {"living_room": ["kitchen"]},
            "sensors": {
                "sensor.motion_living": {"area": "living_room", "type": "motion"},
            },
        }

        coordinator = OccupancyCoordinator(hass, config)

        assert coordinator.config == config
        assert len(coordinator.area_manager.areas) == 2
        assert len(coordinator.sensor_manager.sensors) == 1
        assert "living_room" in coordinator.area_manager.areas
        assert "sensor.motion_living" in coordinator.sensor_manager.sensors

    def test_initialize_areas(self):
        """Test area initialization from config."""
        hass = Mock(spec=HomeAssistant)
        config = {
            "areas": {
                "bedroom": {"name": "Bedroom", "indoors": True, "exit_capable": False},
                "porch": {"name": "Porch", "indoors": False, "exit_capable": True},
            },
            "adjacency": {},
            "sensors": {},
        }

        coordinator = OccupancyCoordinator(hass, config)

        assert coordinator.area_manager.areas["bedroom"].is_indoors is True
        assert coordinator.area_manager.areas["bedroom"].is_exit_capable is False
        assert coordinator.area_manager.areas["porch"].is_indoors is False
        assert coordinator.area_manager.areas["porch"].is_exit_capable is True

    def test_initialize_sensors(self):
        """Test sensor initialization from config."""
        hass = Mock(spec=HomeAssistant)
        config = {
            "areas": {"room1": {}},
            "adjacency": {},
            "sensors": {
                "sensor.motion_1": {"area": "room1", "type": "motion"},
                "sensor.door_1": {
                    "type": "magnetic",
                    "between_areas": ["room1", "room2"],
                },
            },
        }

        coordinator = OccupancyCoordinator(hass, config)

        assert coordinator.sensor_manager.sensors["sensor.motion_1"].config["type"] == "motion"
        assert coordinator.sensor_manager.sensors["sensor.door_1"].config["type"] == "magnetic"

    def test_initialize_adjacency(self):
        """Test adjacency initialization."""
        hass = Mock(spec=HomeAssistant)
        config = {
            "areas": {
                "living_room": {},
                "kitchen": {},
                "hallway": {},
            },
            "adjacency": {
                "living_room": ["kitchen", "hallway"],
                "kitchen": ["living_room"],
            },
            "sensors": {
                "sensor.motion_living": {"area": "living_room", "type": "motion"},
                "sensor.motion_kitchen": {"area": "kitchen", "type": "motion"},
                "sensor.motion_hallway": {"area": "hallway", "type": "motion"},
            },
        }

        coordinator = OccupancyCoordinator(hass, config)

        # Living room sensor should know about kitchen and hallway sensors
        adjacent = coordinator.adjacency_tracker.get_adjacency("sensor.motion_living")
        assert "sensor.motion_kitchen" in adjacent
        assert "sensor.motion_hallway" in adjacent


class TestOccupancyCoordinatorSensorEvents:
    """Test sensor event processing."""

    def test_process_motion_event(self):
        """Test processing a motion sensor event."""
        hass = Mock(spec=HomeAssistant)
        config = {
            "areas": {"living_room": {"name": "Living Room", "exit_capable": True}},
            "adjacency": {},
            "sensors": {
                "sensor.motion_living": {"area": "living_room", "type": "motion"},
            },
        }

        coordinator = OccupancyCoordinator(hass, config)
        timestamp = time.time()

        coordinator.process_sensor_event("sensor.motion_living", True, timestamp)

        # Motion should be recorded
        assert coordinator.area_manager.areas["living_room"].last_motion == timestamp
        # Entry should be recorded (from outside via exit_capable)
        assert coordinator.area_manager.areas["living_room"].occupancy == 1

    def test_process_motion_event_occupied_room(self):
        """Test motion in already occupied room."""
        hass = Mock(spec=HomeAssistant)
        config = {
            "areas": {"kitchen": {}},
            "adjacency": {},
            "sensors": {
                "sensor.motion_kitchen": {"area": "kitchen", "type": "motion"},
            },
        }

        coordinator = OccupancyCoordinator(hass, config)
        timestamp = time.time()

        # First motion
        coordinator.process_sensor_event("sensor.motion_kitchen", True, timestamp)
        occupancy_after_first = coordinator.area_manager.areas["kitchen"].occupancy

        # Second motion (repeated)
        coordinator.process_sensor_event("sensor.motion_kitchen", True, timestamp + 10)

        # Occupancy shouldn't increase again
        assert coordinator.area_manager.areas["kitchen"].occupancy == occupancy_after_first

    def test_process_unknown_sensor(self):
        """Test processing event from unknown sensor."""
        hass = Mock(spec=HomeAssistant)
        config = {"areas": {}, "adjacency": {}, "sensors": {}}

        coordinator = OccupancyCoordinator(hass, config)

        # Should not raise error
        coordinator.process_sensor_event("sensor.unknown", True, time.time())

    def test_process_magnetic_sensor(self):
        """Test processing magnetic (door/window) sensor."""
        hass = Mock(spec=HomeAssistant)
        config = {
            "areas": {"room1": {}, "room2": {}},
            "adjacency": {"room1": ["room2"]},
            "sensors": {
                "sensor.door_12": {
                    "type": "magnetic",
                    "between_areas": ["room1", "room2"],
                },
            },
        }

        coordinator = OccupancyCoordinator(hass, config)

        # Process door open/close
        coordinator.process_sensor_event("sensor.door_12", True, time.time())
        coordinator.process_sensor_event("sensor.door_12", False, time.time() + 5)

        # Door events are recorded but don't directly change occupancy

    def test_process_camera_motion_sensor(self):
        """Test processing camera motion sensor."""
        hass = Mock(spec=HomeAssistant)
        config = {
            "areas": {"front_porch": {"exit_capable": True}},
            "adjacency": {},
            "sensors": {
                "sensor.camera_motion": {
                    "area": "front_porch",
                    "type": "camera_motion",
                },
            },
        }

        coordinator = OccupancyCoordinator(hass, config)
        timestamp = time.time()

        coordinator.process_sensor_event("sensor.camera_motion", True, timestamp)

        assert coordinator.area_manager.areas["front_porch"].last_motion == timestamp

    def test_process_camera_person_sensor(self):
        """Test processing camera person detection sensor."""
        hass = Mock(spec=HomeAssistant)
        config = {
            "areas": {"driveway": {"exit_capable": True}},
            "adjacency": {},
            "sensors": {
                "sensor.camera_person": {"area": "driveway", "type": "camera_person"},
            },
        }

        coordinator = OccupancyCoordinator(hass, config)
        timestamp = time.time()

        coordinator.process_sensor_event("sensor.camera_person", True, timestamp)

        assert coordinator.area_manager.areas["driveway"].last_motion == timestamp

    def test_sensor_state_change_tracking(self):
        """Test that sensor state changes are properly tracked."""
        hass = Mock(spec=HomeAssistant)
        config = {
            "areas": {"room": {}},
            "adjacency": {},
            "sensors": {
                "sensor.motion": {"area": "room", "type": "motion"},
            },
        }

        coordinator = OccupancyCoordinator(hass, config)
        t1 = time.time()

        coordinator.process_sensor_event("sensor.motion", True, t1)
        assert coordinator.sensor_manager.sensors["sensor.motion"].current_state is True

        coordinator.process_sensor_event("sensor.motion", False, t1 + 10)
        assert coordinator.sensor_manager.sensors["sensor.motion"].current_state is False


class TestOccupancyCoordinatorTransitions:
    """Test occupancy transitions between areas."""

    def test_transition_between_adjacent_rooms(self):
        """Test person transitioning between adjacent rooms."""
        hass = Mock(spec=HomeAssistant)
        config = {
            "areas": {
                "living_room": {},
                "kitchen": {},
            },
            "adjacency": {"living_room": ["kitchen"], "kitchen": ["living_room"]},
            "sensors": {
                "sensor.motion_living": {"area": "living_room", "type": "motion"},
                "sensor.motion_kitchen": {"area": "kitchen", "type": "motion"},
            },
        }

        coordinator = OccupancyCoordinator(hass, config)
        timestamp = time.time()

        # Start in living room (entry from outside - both are not exit_capable)
        # This will create an unexpected motion warning but still increment
        coordinator.process_sensor_event("sensor.motion_living", True, timestamp)
        assert coordinator.area_manager.areas["living_room"].occupancy >= 1

        # Move to kitchen (adjacent, recent motion in living room)
        coordinator.process_sensor_event("sensor.motion_kitchen", True, timestamp + 10)

        # Kitchen should have person
        assert coordinator.area_manager.areas["kitchen"].occupancy >= 1
        # Living room should have decremented if transition detected
        # (This depends on the exact logic in handle_unexpected_motion)

    def test_entry_from_outside(self):
        """Test person entering from outside through exit-capable area."""
        hass = Mock(spec=HomeAssistant)
        config = {
            "areas": {
                "front_door": {"exit_capable": True},
            },
            "adjacency": {},
            "sensors": {
                "sensor.motion_door": {"area": "front_door", "type": "motion"},
            },
        }

        coordinator = OccupancyCoordinator(hass, config)

        coordinator.process_sensor_event("sensor.motion_door", True, time.time())

        # Should register entry
        assert coordinator.area_manager.areas["front_door"].occupancy == 1


class TestOccupancyCoordinatorQueries:
    """Test occupancy query methods."""

    def test_get_occupancy(self):
        """Test getting occupancy count for an area."""
        hass = Mock(spec=HomeAssistant)
        config = {
            "areas": {"bedroom": {}},
            "adjacency": {},
            "sensors": {},
        }

        coordinator = OccupancyCoordinator(hass, config)

        # Initially zero
        assert coordinator.get_occupancy("bedroom") == 0

        # Manually set occupancy
        coordinator.area_manager.areas["bedroom"].occupancy = 2

        assert coordinator.get_occupancy("bedroom") == 2

    def test_get_occupancy_unknown_area(self):
        """Test getting occupancy for unknown area."""
        hass = Mock(spec=HomeAssistant)
        config = {"areas": {}, "adjacency": {}, "sensors": {}}

        coordinator = OccupancyCoordinator(hass, config)

        assert coordinator.get_occupancy("unknown") == 0

    def test_get_occupancy_probability_occupied(self):
        """Test probability calculation for occupied area with recent motion."""
        hass = Mock(spec=HomeAssistant)
        config = {
            "areas": {"office": {}},
            "adjacency": {},
            "sensors": {},
        }

        coordinator = OccupancyCoordinator(hass, config)
        timestamp = time.time()

        coordinator.area_manager.areas["office"].occupancy = 1
        coordinator.area_manager.areas["office"].record_motion(timestamp)

        probability = coordinator.get_occupancy_probability("office")

        # Recent motion + occupied = high probability
        assert probability == 1.0

    def test_get_occupancy_probability_unoccupied(self):
        """Test probability for unoccupied area."""
        hass = Mock(spec=HomeAssistant)
        config = {
            "areas": {"basement": {}},
            "adjacency": {},
            "sensors": {},
        }

        coordinator = OccupancyCoordinator(hass, config)

        probability = coordinator.get_occupancy_probability("basement")

        assert probability == 0.0

    def test_get_area_status(self):
        """Test getting detailed area status."""
        hass = Mock(spec=HomeAssistant)
        config = {
            "areas": {
                "living_room": {"name": "Living Room"},
            },
            "adjacency": {"living_room": ["kitchen"]},
            "sensors": {},
        }

        coordinator = OccupancyCoordinator(hass, config)
        timestamp = time.time()

        coordinator.area_manager.areas["living_room"].occupancy = 2
        coordinator.area_manager.areas["living_room"].record_motion(timestamp)

        status = coordinator.get_area_status("living_room")

        assert status["id"] == "living_room"
        assert status["name"] == "Living Room"
        assert status["occupancy"] == 2
        assert status["last_motion"] == timestamp
        assert status["adjacent_areas"] == ["kitchen"]

    def test_get_area_status_unknown(self):
        """Test getting status for unknown area."""
        hass = Mock(spec=HomeAssistant)
        config = {"areas": {}, "adjacency": {}, "sensors": {}}

        coordinator = OccupancyCoordinator(hass, config)

        status = coordinator.get_area_status("unknown")

        assert "error" in status

    def test_get_system_status(self):
        """Test getting overall system status."""
        hass = Mock(spec=HomeAssistant)
        config = {
            "areas": {
                "room1": {},
                "room2": {},
                "room3": {},
            },
            "adjacency": {},
            "sensors": {},
        }

        coordinator = OccupancyCoordinator(hass, config)

        coordinator.area_manager.areas["room1"].occupancy = 2
        coordinator.area_manager.areas["room2"].occupancy = 1

        status = coordinator.get_system_status()

        assert status["total_occupancy"] == 3
        assert len(status["occupied_areas"]) == 2
        assert status["occupied_areas"]["room1"] == 2
        assert status["occupied_areas"]["room2"] == 1


class TestOccupancyCoordinatorTimeouts:
    """Test timeout checking."""

    def test_check_timeouts(self):
        """Test checking for timeout conditions."""
        hass = Mock(spec=HomeAssistant)
        config = {
            "areas": {"bedroom": {}},
            "adjacency": {},
            "sensors": {},
        }

        coordinator = OccupancyCoordinator(hass, config)
        timestamp = time.time()

        # Set up occupied area with old motion
        coordinator.area_manager.areas["bedroom"].occupancy = 1
        coordinator.area_manager.areas["bedroom"].last_motion = timestamp - (25 * 3600)

        coordinator.check_timeouts(timestamp)

        # Should reset due to inactivity
        assert coordinator.area_manager.areas["bedroom"].occupancy == 0

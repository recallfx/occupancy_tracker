"""Tests for MapOccupancyResolver motion-off behavior."""

import time

from custom_components.occupancy_tracker.helpers.map_occupancy_resolver import (
    MapOccupancyResolver,
)
from custom_components.occupancy_tracker.helpers.anomaly_detector import (
    AnomalyDetector,
)
from custom_components.occupancy_tracker.helpers.area_state import AreaState
from custom_components.occupancy_tracker.helpers.sensor_state import SensorState
from custom_components.occupancy_tracker.helpers.map_state_recorder import MapSnapshot


def _sensor_event(sensor_id: str, on: bool, ts: float) -> MapSnapshot:
    return MapSnapshot(
        timestamp=ts,
        event_type="sensor",
        description=f"sensor:{sensor_id}:{'on' if on else 'off'}",
        areas={},
        sensors={},
    )


def test_motion_off_ignores_stale_neighbor_activation():
    """Hall should not clear due to distant frontyard activation."""
    now = time.time()
    config = {
        "areas": {
            "front_hall": {"name": "Front Hall", "transition": True},
            "frontyard": {"name": "Front Yard", "transition": True, "exit_capable": True, "indoors": False},
        },
        "adjacency": {
            "front_hall": ["frontyard"],
            "frontyard": ["front_hall"],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "front_hall": AreaState("front_hall", config["areas"]["front_hall"]),
        "frontyard": AreaState("frontyard", config["areas"]["frontyard"]),
    }
    sensors = {
        "binary_sensor.hall": SensorState(
            "binary_sensor.hall", {"area": "front_hall", "type": "motion"}, now
        ),
        "binary_sensor.frontyard": SensorState(
            "binary_sensor.frontyard", {"area": "frontyard", "type": "motion"}, now
        ),
        "binary_sensor.front_door": SensorState(
            "binary_sensor.front_door", {"area": ["front_hall", "frontyard"], "type": "door"}, now
        ),
    }

    # Door opens (magnetic evidence for possible entry)
    resolver.process_snapshot(_sensor_event("binary_sensor.front_door", True, now - 1), areas, sensors, detector)

    # Person in hall, hall motion turns on
    resolver.process_snapshot(_sensor_event("binary_sensor.hall", True, now), areas, sensors, detector)
    assert areas["front_hall"].occupancy == 1

    # Much later, frontyard motion turns on (different person outside)
    resolver.process_snapshot(_sensor_event("binary_sensor.frontyard", True, now + 100), areas, sensors, detector)
    assert areas["frontyard"].occupancy == 1

    # Hall sensor finally turns off; since neighbor activation was long ago, hall should stay occupied
    resolver.process_snapshot(_sensor_event("binary_sensor.hall", False, now + 110), areas, sensors, detector)

    assert areas["front_hall"].occupancy == 1
    assert areas["frontyard"].occupancy == 1


def test_intrusion_warning_outdoor_then_indoor_motion():
    """Outdoor activation followed by indoor motion should raise intrusion warning when no indoor source exists."""
    now = time.time()
    config = {
        "areas": {
            "foyer": {"name": "Foyer", "indoors": True},
            "frontyard": {"name": "Front Yard", "indoors": False, "exit_capable": True},
        },
        "adjacency": {
            "foyer": ["frontyard"],
            "frontyard": ["foyer"],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "foyer": AreaState("foyer", config["areas"]["foyer"]),
        "frontyard": AreaState("frontyard", config["areas"]["frontyard"]),
    }
    sensors = {
        "binary_sensor.frontyard": SensorState(
            "binary_sensor.frontyard", {"area": "frontyard", "type": "motion"}, now
        ),
        "binary_sensor.foyer": SensorState(
            "binary_sensor.foyer", {"area": "foyer", "type": "motion"}, now
        ),
    }

    # Outside motion starts first (unknown presence)
    resolver.process_snapshot(_sensor_event("binary_sensor.frontyard", True, now), areas, sensors, detector)

    # Indoor motion follows shortly after with no indoor source
    resolver.process_snapshot(_sensor_event("binary_sensor.foyer", True, now + 2), areas, sensors, detector)

    assert areas["foyer"].occupancy == 1

    warnings = detector.get_warnings()
    assert len(warnings) == 1
    assert warnings[0].type == "unexpected_motion"
    assert "intrusion_outside_adjacent" in warnings[0].message


def test_outdoor_then_magnetic_then_indoor_suppresses_intrusion_warning():
    """Magnetic event between outdoor and indoor should allow entry without intrusion warning."""
    now = time.time()
    config = {
        "areas": {
            "foyer": {"name": "Foyer", "indoors": True},
            "frontyard": {"name": "Front Yard", "indoors": False, "exit_capable": True},
        },
        "adjacency": {
            "foyer": ["frontyard"],
            "frontyard": ["foyer"],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "foyer": AreaState("foyer", config["areas"]["foyer"]),
        "frontyard": AreaState("frontyard", config["areas"]["frontyard"]),
    }
    sensors = {
        "binary_sensor.frontyard": SensorState(
            "binary_sensor.frontyard", {"area": "frontyard", "type": "motion"}, now
        ),
        "binary_sensor.door": SensorState(
            "binary_sensor.door", {"area": ["foyer", "frontyard"], "type": "magnetic"}, now
        ),
        "binary_sensor.foyer": SensorState(
            "binary_sensor.foyer", {"area": "foyer", "type": "motion"}, now
        ),
    }

    resolver.process_snapshot(_sensor_event("binary_sensor.frontyard", True, now), areas, sensors, detector)
    resolver.process_snapshot(_sensor_event("binary_sensor.door", True, now + 1), areas, sensors, detector)
    resolver.process_snapshot(_sensor_event("binary_sensor.foyer", True, now + 2), areas, sensors, detector)

    assert areas["foyer"].occupancy == 1
    warnings = detector.get_warnings()
    assert warnings == []


def test_indoor_activation_ignored_without_outdoor_or_magnet():
    """Indoor motion with no occupants, no adjacent outdoor activity, and no magnet should be ignored and warned."""
    now = time.time()
    config = {
        "areas": {
            "office": {"name": "Office", "indoors": True},
        },
        "adjacency": {
            "office": [],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "office": AreaState("office", config["areas"]["office"]),
    }
    sensors = {
        "binary_sensor.office_motion": SensorState(
            "binary_sensor.office_motion", {"area": "office", "type": "motion"}, now
        ),
    }

    resolver.process_snapshot(_sensor_event("binary_sensor.office_motion", True, now), areas, sensors, detector)

    # No outdoor adjacency, so activation is allowed but still warned as unexplained
    assert areas["office"].occupancy == 1
    warnings = detector.get_warnings()
    assert len(warnings) == 1
    assert warnings[0].type == "unexpected_motion"
    assert "no_adjacent_source" in warnings[0].message

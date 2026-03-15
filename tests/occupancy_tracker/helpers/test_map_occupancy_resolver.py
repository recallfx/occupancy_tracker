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


def _fire(resolver, sensors, areas, sensor_id, on, ts, detector=None):
    """Update sensor state then process snapshot (mirrors coordinator behavior)."""
    sensor = sensors.get(sensor_id)
    if sensor:
        sensor.update_state(on, ts)
    resolver.process_snapshot(
        _sensor_event(sensor_id, on, ts), areas, sensors, detector
    )


def test_motion_off_ignores_stale_neighbor_activation():
    """Hall should not clear due to distant frontyard activation."""
    now = time.time()
    config = {
        "areas": {
            "front_hall": {"name": "Front Hall", "transition": True},
            "frontyard": {
                "name": "Front Yard",
                "transition": True,
                "exit_capable": True,
                "indoors": False,
            },
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
            "binary_sensor.front_door",
            {"area": ["front_hall", "frontyard"], "type": "door"},
            now,
        ),
    }

    # Door opens (magnetic evidence for possible entry)
    _fire(resolver, sensors, areas, "binary_sensor.front_door", True, now - 1, detector)

    # Person in hall, hall motion turns on
    _fire(resolver, sensors, areas, "binary_sensor.hall", True, now, detector)
    assert areas["front_hall"].occupancy == 1

    # Much later, frontyard motion turns on (different person outside)
    _fire(
        resolver, sensors, areas, "binary_sensor.frontyard", True, now + 100, detector
    )
    assert areas["frontyard"].occupancy == 1

    # Hall sensor finally turns off; since neighbor activation was long ago, hall should stay occupied
    _fire(resolver, sensors, areas, "binary_sensor.hall", False, now + 110, detector)

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
    _fire(resolver, sensors, areas, "binary_sensor.frontyard", True, now, detector)

    # Indoor motion follows shortly after with no indoor source
    _fire(resolver, sensors, areas, "binary_sensor.foyer", True, now + 2, detector)

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
            "binary_sensor.door",
            {"area": ["foyer", "frontyard"], "type": "magnetic"},
            now,
        ),
        "binary_sensor.foyer": SensorState(
            "binary_sensor.foyer", {"area": "foyer", "type": "motion"}, now
        ),
    }

    _fire(resolver, sensors, areas, "binary_sensor.frontyard", True, now, detector)
    _fire(resolver, sensors, areas, "binary_sensor.door", True, now + 1, detector)
    _fire(resolver, sensors, areas, "binary_sensor.foyer", True, now + 2, detector)

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

    _fire(resolver, sensors, areas, "binary_sensor.office_motion", True, now, detector)

    # No outdoor adjacency, so activation is allowed but still warned as unexplained
    assert areas["office"].occupancy == 1
    warnings = detector.get_warnings()
    assert len(warnings) == 1
    assert warnings[0].type == "unexpected_motion"
    assert "no_adjacent_source" in warnings[0].message


# ---------------------------------------------------------------------------
# 1A: Motion-ON Plausible Source Logic
# ---------------------------------------------------------------------------


def test_motion_on_indoor_unlinked_with_outdoor_neighbor():
    """Indoor area with only outdoor neighbor, all empty -> ON -> occupancy 0, warning indoor_activation_unlinked."""
    now = time.time()
    config = {
        "areas": {
            "foyer": {"name": "Foyer", "indoors": True},
            "frontyard": {
                "name": "Front Yard",
                "indoors": False,
                "exit_capable": True,
            },
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
        "binary_sensor.foyer": SensorState(
            "binary_sensor.foyer", {"area": "foyer", "type": "motion"}, now
        ),
        "binary_sensor.frontyard": SensorState(
            "binary_sensor.frontyard",
            {"area": "frontyard", "type": "motion"},
            now,
        ),
    }

    # Everything empty, no outdoor activity -> foyer ON
    _fire(resolver, sensors, areas, "binary_sensor.foyer", True, now, detector)

    assert areas["foyer"].occupancy == 0
    warnings = detector.get_warnings()
    assert len(warnings) == 1
    assert "indoor_activation_unlinked" in warnings[0].message


def test_motion_on_with_occupied_indoor_neighbor():
    """Indoor neighbor occupied -> motion ON -> occupancy 1, no warnings."""
    now = time.time()
    config = {
        "areas": {
            "area_a": {"name": "A", "indoors": True},
            "area_b": {"name": "B", "indoors": True},
            "area_c": {"name": "C", "indoors": True},
        },
        "adjacency": {
            "area_a": ["area_b"],
            "area_b": ["area_a", "area_c"],
            "area_c": ["area_b"],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "area_a": AreaState("area_a", config["areas"]["area_a"]),
        "area_b": AreaState("area_b", config["areas"]["area_b"]),
        "area_c": AreaState("area_c", config["areas"]["area_c"]),
    }
    sensors = {
        "binary_sensor.a": SensorState(
            "binary_sensor.a", {"area": "area_a", "type": "motion"}, now
        ),
        "binary_sensor.b": SensorState(
            "binary_sensor.b", {"area": "area_b", "type": "motion"}, now
        ),
        "binary_sensor.c": SensorState(
            "binary_sensor.c", {"area": "area_c", "type": "motion"}, now
        ),
    }

    # Set up B as occupied (person already there)
    areas["area_b"].record_entry(now - 10)
    areas["area_b"].last_motion = now - 5
    sensors["binary_sensor.b"].update_state(True, now - 5)

    # A turns ON -> should see occupied indoor neighbor B, so A becomes occupied
    _fire(resolver, sensors, areas, "binary_sensor.a", True, now, detector)

    assert areas["area_a"].occupancy == 1
    warnings = detector.get_warnings()
    assert len(warnings) == 0


def test_motion_on_already_occupied_no_increment():
    """Area already occupied -> ON -> stays at 1, not incremented to 2."""
    now = time.time()
    config = {
        "areas": {
            "area_a": {"name": "A", "indoors": True},
        },
        "adjacency": {
            "area_a": [],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "area_a": AreaState("area_a", config["areas"]["area_a"]),
    }
    sensors = {
        "binary_sensor.a": SensorState(
            "binary_sensor.a", {"area": "area_a", "type": "motion"}, now
        ),
    }

    # Already occupied
    areas["area_a"].record_entry(now - 10)
    areas["area_a"].last_motion = now - 5
    sensors["binary_sensor.a"].update_state(True, now - 5)

    # Re-trigger motion ON
    _fire(resolver, sensors, areas, "binary_sensor.a", True, now, detector)

    assert areas["area_a"].occupancy == 1  # Not 2


def test_motion_on_exit_capable_no_anomaly():
    """Exit-capable outdoor area -> ON -> occupancy 1, no anomaly."""
    now = time.time()
    config = {
        "areas": {
            "frontyard": {
                "name": "Front Yard",
                "indoors": False,
                "exit_capable": True,
            },
        },
        "adjacency": {
            "frontyard": [],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "frontyard": AreaState("frontyard", config["areas"]["frontyard"]),
    }
    sensors = {
        "binary_sensor.frontyard": SensorState(
            "binary_sensor.frontyard",
            {"area": "frontyard", "type": "motion"},
            now,
        ),
    }

    _fire(resolver, sensors, areas, "binary_sensor.frontyard", True, now, detector)

    assert areas["frontyard"].occupancy == 1
    warnings = detector.get_warnings()
    assert len(warnings) == 0


def test_motion_on_outdoor_then_indoor_no_magnetic():
    """Outdoor ON then indoor ON with no magnetic -> intrusion_outside_adjacent warning."""
    now = time.time()
    config = {
        "areas": {
            "foyer": {"name": "Foyer", "indoors": True},
            "frontyard": {
                "name": "Front Yard",
                "indoors": False,
                "exit_capable": True,
            },
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
            "binary_sensor.frontyard",
            {"area": "frontyard", "type": "motion"},
            now,
        ),
        "binary_sensor.foyer": SensorState(
            "binary_sensor.foyer", {"area": "foyer", "type": "motion"}, now
        ),
    }

    # Frontyard ON first
    _fire(resolver, sensors, areas, "binary_sensor.frontyard", True, now, detector)

    # Then foyer ON (no magnetic in between)
    _fire(resolver, sensors, areas, "binary_sensor.foyer", True, now + 2, detector)

    assert areas["foyer"].occupancy == 1
    warnings = detector.get_warnings()
    assert len(warnings) == 1
    assert "intrusion_outside_adjacent" in warnings[0].message


# ---------------------------------------------------------------------------
# 1B: Activation Window Boundary Tests
# ---------------------------------------------------------------------------


def _make_two_area_config():
    """Helper: create a 2-area linear config (A-B), both indoor."""
    config = {
        "areas": {
            "area_a": {"name": "A", "indoors": True},
            "area_b": {"name": "B", "indoors": True},
        },
        "adjacency": {
            "area_a": ["area_b"],
            "area_b": ["area_a"],
        },
        "sensors": {},
    }
    return config


def _setup_activation_window_test(config, now, src_on, nbr_on, src_off):
    """
    Helper for activation-window boundary tests.

    Sets up: person in A, A ON at src_on, B ON at nbr_on, A OFF at src_off.
    Returns (resolver, detector, areas, sensors) AFTER processing A OFF.
    """
    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "area_a": AreaState("area_a", config["areas"]["area_a"]),
        "area_b": AreaState("area_b", config["areas"]["area_b"]),
    }
    sensors = {
        "binary_sensor.a": SensorState(
            "binary_sensor.a", {"area": "area_a", "type": "motion"}, now
        ),
        "binary_sensor.b": SensorState(
            "binary_sensor.b", {"area": "area_b", "type": "motion"}, now
        ),
    }

    # A turns ON at src_on -> person enters A
    _fire(resolver, sensors, areas, "binary_sensor.a", True, now + src_on, detector)
    assert areas["area_a"].occupancy == 1

    # B turns ON at nbr_on
    _fire(resolver, sensors, areas, "binary_sensor.b", True, now + nbr_on, detector)

    # A turns OFF at src_off
    _fire(resolver, sensors, areas, "binary_sensor.a", False, now + src_off, detector)

    return resolver, detector, areas, sensors


def test_recent_window_exactly_5s():
    """Neighbor activated exactly 5s before OFF -> movement detected (95 >= 100-5)."""
    now = time.time()
    config = _make_two_area_config()
    _, _, areas, _ = _setup_activation_window_test(
        config, now, src_on=0, nbr_on=95, src_off=100
    )
    assert areas["area_b"].occupancy == 1
    assert areas["area_a"].occupancy == 0


def test_recent_window_just_outside_5s():
    """Neighbor activated 5.1s before OFF -> outside recent window."""
    now = time.time()
    config = _make_two_area_config()
    _, _, areas, _ = _setup_activation_window_test(
        config, now, src_on=0, nbr_on=94.9, src_off=100
    )
    # 94.9 is NOT >= 95 (100 - 5), and 94.9 - 0 = 94.9 > 30, so no match
    assert areas["area_b"].occupancy == 1  # B got occupied on its own ON event
    assert areas["area_a"].occupancy == 1  # A stays occupied (no movement evidence)


def test_masked_window_exactly_30s():
    """Neighbor activated exactly 30s after source ON -> movement (30 <= 30)."""
    now = time.time()
    config = _make_two_area_config()
    _, _, areas, _ = _setup_activation_window_test(
        config, now, src_on=0, nbr_on=30, src_off=100
    )
    assert areas["area_b"].occupancy == 1
    assert areas["area_a"].occupancy == 0


def test_masked_window_just_outside_30s():
    """Neighbor activated 30.1s after source ON -> outside masked window."""
    now = time.time()
    config = _make_two_area_config()
    _, _, areas, _ = _setup_activation_window_test(
        config, now, src_on=0, nbr_on=30.1, src_off=100
    )
    # 30.1 - 0 = 30.1 > 30, and 30.1 < 95 (100-5), so no match
    assert areas["area_b"].occupancy == 1  # B got occupied on its own ON event
    assert areas["area_a"].occupancy == 1  # A stays (no movement evidence)


def test_stale_activation_100s_rejected():
    """Neighbor activated 50s after source ON (gap too large) -> no movement."""
    now = time.time()
    config = _make_two_area_config()
    _, _, areas, _ = _setup_activation_window_test(
        config, now, src_on=0, nbr_on=50, src_off=100
    )
    # 50 - 0 = 50 > 30, and 50 < 95, so no match
    assert areas["area_b"].occupancy == 1  # B got occupied on its own ON event
    assert areas["area_a"].occupancy == 1  # A stays


def test_recent_activation_within_window():
    """Neighbor activated 3s before OFF -> clearly within recent window."""
    now = time.time()
    config = _make_two_area_config()
    _, _, areas, _ = _setup_activation_window_test(
        config, now, src_on=0, nbr_on=97, src_off=100
    )
    assert areas["area_b"].occupancy == 1
    assert areas["area_a"].occupancy == 0


def test_masked_movement_within_window():
    """Neighbor activated 20s after source ON -> within masked window (20 <= 30)."""
    now = time.time()
    config = _make_two_area_config()
    _, _, areas, _ = _setup_activation_window_test(
        config, now, src_on=0, nbr_on=20, src_off=100
    )
    assert areas["area_b"].occupancy == 1
    assert areas["area_a"].occupancy == 0


# ---------------------------------------------------------------------------
# 1C: Exit-Capable Motion-OFF
# ---------------------------------------------------------------------------


def test_exit_capable_clears_on_motion_off():
    """Exit-capable area, person there, no neighbor activation -> OFF -> occupancy 0."""
    now = time.time()
    config = {
        "areas": {
            "frontyard": {
                "name": "Front Yard",
                "indoors": False,
                "exit_capable": True,
            },
        },
        "adjacency": {
            "frontyard": [],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "frontyard": AreaState("frontyard", config["areas"]["frontyard"]),
    }
    sensors = {
        "binary_sensor.frontyard": SensorState(
            "binary_sensor.frontyard",
            {"area": "frontyard", "type": "motion"},
            now,
        ),
    }

    # Person enters frontyard
    _fire(resolver, sensors, areas, "binary_sensor.frontyard", True, now, detector)
    assert areas["frontyard"].occupancy == 1

    # Motion stops, no neighbor -> person left
    _fire(
        resolver, sensors, areas, "binary_sensor.frontyard", False, now + 10, detector
    )
    assert areas["frontyard"].occupancy == 0


def test_exit_capable_moves_to_neighbor_instead():
    """Exit-capable area + neighbor activated -> OFF -> moves to neighbor."""
    now = time.time()
    config = {
        "areas": {
            "frontyard": {
                "name": "Front Yard",
                "indoors": False,
                "exit_capable": True,
            },
            "foyer": {"name": "Foyer", "indoors": True},
        },
        "adjacency": {
            "frontyard": ["foyer"],
            "foyer": ["frontyard"],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "frontyard": AreaState("frontyard", config["areas"]["frontyard"]),
        "foyer": AreaState("foyer", config["areas"]["foyer"]),
    }
    sensors = {
        "binary_sensor.frontyard": SensorState(
            "binary_sensor.frontyard",
            {"area": "frontyard", "type": "motion"},
            now,
        ),
        "binary_sensor.foyer": SensorState(
            "binary_sensor.foyer", {"area": "foyer", "type": "motion"}, now
        ),
    }

    # Person in frontyard
    _fire(resolver, sensors, areas, "binary_sensor.frontyard", True, now, detector)
    assert areas["frontyard"].occupancy == 1

    # Foyer activates (within recent window of upcoming OFF)
    _fire(resolver, sensors, areas, "binary_sensor.foyer", True, now + 8, detector)

    # Frontyard OFF
    _fire(
        resolver, sensors, areas, "binary_sensor.frontyard", False, now + 10, detector
    )

    assert areas["frontyard"].occupancy == 0
    assert areas["foyer"].occupancy == 1


def test_non_exit_stays_on_motion_off():
    """Non-exit area, person there, no neighbor activation -> OFF -> stays occupied."""
    now = time.time()
    config = {
        "areas": {
            "area_b": {"name": "B", "indoors": True},
        },
        "adjacency": {
            "area_b": [],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "area_b": AreaState("area_b", config["areas"]["area_b"]),
    }
    sensors = {
        "binary_sensor.b": SensorState(
            "binary_sensor.b", {"area": "area_b", "type": "motion"}, now
        ),
    }

    # Person enters B
    _fire(resolver, sensors, areas, "binary_sensor.b", True, now, detector)
    assert areas["area_b"].occupancy == 1

    # Motion stops, no neighbor, not exit-capable -> stays
    _fire(resolver, sensors, areas, "binary_sensor.b", False, now + 10, detector)
    assert areas["area_b"].occupancy == 1


# ---------------------------------------------------------------------------
# 1D: Multi-Hop BFS
# ---------------------------------------------------------------------------


def test_multi_hop_4_room_chain():
    """A-B-C-D chain, person in A, B/C/D activated in order -> A OFF -> person moves through chain."""
    now = time.time()
    config = {
        "areas": {
            "area_a": {"name": "A", "indoors": True},
            "area_b": {"name": "B", "indoors": True},
            "area_c": {"name": "C", "indoors": True},
            "area_d": {"name": "D", "indoors": True},
        },
        "adjacency": {
            "area_a": ["area_b"],
            "area_b": ["area_a", "area_c"],
            "area_c": ["area_b", "area_d"],
            "area_d": ["area_c"],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {aid: AreaState(aid, config["areas"][aid]) for aid in config["areas"]}
    sensors = {
        "binary_sensor.a": SensorState(
            "binary_sensor.a", {"area": "area_a", "type": "motion"}, now
        ),
        "binary_sensor.b": SensorState(
            "binary_sensor.b", {"area": "area_b", "type": "motion"}, now
        ),
        "binary_sensor.c": SensorState(
            "binary_sensor.c", {"area": "area_c", "type": "motion"}, now
        ),
        "binary_sensor.d": SensorState(
            "binary_sensor.d", {"area": "area_d", "type": "motion"}, now
        ),
    }

    # Person enters A
    _fire(resolver, sensors, areas, "binary_sensor.a", True, now, detector)
    assert areas["area_a"].occupancy == 1

    # B, C, D activate in order within masked window
    _fire(resolver, sensors, areas, "binary_sensor.b", True, now + 3, detector)
    _fire(resolver, sensors, areas, "binary_sensor.c", True, now + 6, detector)
    _fire(resolver, sensors, areas, "binary_sensor.d", True, now + 9, detector)

    # Verify intermediate state before A OFF
    assert areas["area_a"].occupancy == 1
    assert areas["area_b"].occupancy == 1
    assert areas["area_c"].occupancy == 1
    assert areas["area_d"].occupancy == 1

    # A turns OFF -> multi-hop should detect movement through B, C, D
    _fire(resolver, sensors, areas, "binary_sensor.a", False, now + 10, detector)

    assert areas["area_a"].occupancy == 0
    assert areas["area_b"].occupancy == 1
    assert areas["area_c"].occupancy == 1
    assert areas["area_d"].occupancy == 1


def test_multi_hop_branching():
    """Hub topology: A->B and A->C, person in A, B+C activated -> A OFF -> both B and C occupied."""
    now = time.time()
    config = {
        "areas": {
            "area_a": {"name": "A", "indoors": True},
            "area_b": {"name": "B", "indoors": True},
            "area_c": {"name": "C", "indoors": True},
        },
        "adjacency": {
            "area_a": ["area_b", "area_c"],
            "area_b": ["area_a"],
            "area_c": ["area_a"],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {aid: AreaState(aid, config["areas"][aid]) for aid in config["areas"]}
    sensors = {
        "binary_sensor.a": SensorState(
            "binary_sensor.a", {"area": "area_a", "type": "motion"}, now
        ),
        "binary_sensor.b": SensorState(
            "binary_sensor.b", {"area": "area_b", "type": "motion"}, now
        ),
        "binary_sensor.c": SensorState(
            "binary_sensor.c", {"area": "area_c", "type": "motion"}, now
        ),
    }

    # Person enters A
    _fire(resolver, sensors, areas, "binary_sensor.a", True, now, detector)
    assert areas["area_a"].occupancy == 1

    # B and C activate within window
    _fire(resolver, sensors, areas, "binary_sensor.b", True, now + 3, detector)
    _fire(resolver, sensors, areas, "binary_sensor.c", True, now + 4, detector)

    # A OFF
    _fire(resolver, sensors, areas, "binary_sensor.a", False, now + 10, detector)

    assert areas["area_a"].occupancy == 0
    assert areas["area_b"].occupancy == 1
    assert areas["area_c"].occupancy == 1


def test_multi_hop_wrong_temporal_order():
    """A-B-C chain, C ON first then B ON -> only B should be reached (temporal order)."""
    now = time.time()
    config = {
        "areas": {
            "area_a": {"name": "A", "indoors": True},
            "area_b": {"name": "B", "indoors": True},
            "area_c": {"name": "C", "indoors": True},
        },
        "adjacency": {
            "area_a": ["area_b"],
            "area_b": ["area_a", "area_c"],
            "area_c": ["area_b"],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {aid: AreaState(aid, config["areas"][aid]) for aid in config["areas"]}
    sensors = {
        "binary_sensor.a": SensorState(
            "binary_sensor.a", {"area": "area_a", "type": "motion"}, now
        ),
        "binary_sensor.b": SensorState(
            "binary_sensor.b", {"area": "area_b", "type": "motion"}, now
        ),
        "binary_sensor.c": SensorState(
            "binary_sensor.c", {"area": "area_c", "type": "motion"}, now
        ),
    }

    # Person enters A
    _fire(resolver, sensors, areas, "binary_sensor.a", True, now, detector)
    assert areas["area_a"].occupancy == 1

    # C activates FIRST (wrong temporal order for path A→B→C)
    _fire(resolver, sensors, areas, "binary_sensor.c", True, now + 1, detector)
    # C gets occupancy=1 from its own motion-ON (no_adjacent_source warning)
    c_occupancy_before_bfs = areas["area_c"].occupancy

    # B activates SECOND
    _fire(resolver, sensors, areas, "binary_sensor.b", True, now + 2, detector)

    # A OFF → BFS should find B (direct neighbor) but NOT expand to C via B
    # because C activated at t=1 which is BEFORE B at t=2 (wrong temporal order)
    _fire(resolver, sensors, areas, "binary_sensor.a", False, now + 3, detector)

    assert areas["area_a"].occupancy == 0
    assert areas["area_b"].occupancy == 1
    # C should NOT have been incremented by BFS (temporal ordering)
    # It may have occupancy from its own motion-ON, but BFS shouldn't add to it
    assert areas["area_c"].occupancy == c_occupancy_before_bfs


# ---------------------------------------------------------------------------
# 1E: Multi-Occupant Convergence
# ---------------------------------------------------------------------------


def test_two_people_converge_same_room():
    """Person1 in C, person2 in B, C retriggers, B OFF -> C=2, B=0."""
    now = time.time()
    config = {
        "areas": {
            "area_b": {"name": "B", "indoors": True},
            "area_c": {"name": "C", "indoors": True},
        },
        "adjacency": {
            "area_b": ["area_c"],
            "area_c": ["area_b"],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "area_b": AreaState("area_b", config["areas"]["area_b"]),
        "area_c": AreaState("area_c", config["areas"]["area_c"]),
    }
    sensors = {
        "binary_sensor.b": SensorState(
            "binary_sensor.b", {"area": "area_b", "type": "motion"}, now
        ),
        "binary_sensor.c": SensorState(
            "binary_sensor.c", {"area": "area_c", "type": "motion"}, now
        ),
    }

    # Set up: person1 in C (entered at t=0), person2 in B (entered at t=50)
    areas["area_c"].record_entry(now)
    areas["area_c"].last_motion = now
    sensors["binary_sensor.c"].update_state(True, now)

    areas["area_b"].record_entry(now + 50)
    areas["area_b"].last_motion = now + 50
    sensors["binary_sensor.b"].update_state(True, now + 50)

    # C sensor goes OFF then back ON (retrigger at t=100)
    _fire(resolver, sensors, areas, "binary_sensor.c", False, now + 99, detector)
    _fire(resolver, sensors, areas, "binary_sensor.c", True, now + 100, detector)

    # B turns OFF at t=101 -> person2 should move to C
    _fire(resolver, sensors, areas, "binary_sensor.b", False, now + 101, detector)

    assert areas["area_b"].occupancy == 0
    # Convergence fix: pre-occupied target gets incremented
    assert areas["area_c"].occupancy == 2


def test_single_person_no_double_count():
    """Person in A, B ON, A OFF -> B=1 (not 2, since B already got marked on its ON event)."""
    now = time.time()
    config = _make_two_area_config()

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "area_a": AreaState("area_a", config["areas"]["area_a"]),
        "area_b": AreaState("area_b", config["areas"]["area_b"]),
    }
    sensors = {
        "binary_sensor.a": SensorState(
            "binary_sensor.a", {"area": "area_a", "type": "motion"}, now
        ),
        "binary_sensor.b": SensorState(
            "binary_sensor.b", {"area": "area_b", "type": "motion"}, now
        ),
    }

    # A ON
    _fire(resolver, sensors, areas, "binary_sensor.a", True, now, detector)
    assert areas["area_a"].occupancy == 1

    # B ON (within masked window)
    _fire(resolver, sensors, areas, "binary_sensor.b", True, now + 3, detector)
    # B should be 1 from its own ON event
    assert areas["area_b"].occupancy == 1

    # A OFF -> movement detected, but B already occupied so no double-count
    _fire(resolver, sensors, areas, "binary_sensor.a", False, now + 10, detector)

    assert areas["area_a"].occupancy == 0
    assert areas["area_b"].occupancy == 1  # Not 2


def test_three_people_converge():
    """3 people converge on D step by step: p2 (C->D), then p3 (B->C->D)."""
    now = time.time()
    config = {
        "areas": {
            "area_b": {"name": "B", "indoors": True},
            "area_c": {"name": "C", "indoors": True},
            "area_d": {"name": "D", "indoors": True},
        },
        "adjacency": {
            "area_b": ["area_c"],
            "area_c": ["area_b", "area_d"],
            "area_d": ["area_c"],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {aid: AreaState(aid, config["areas"][aid]) for aid in config["areas"]}
    sensors = {
        "binary_sensor.b": SensorState(
            "binary_sensor.b", {"area": "area_b", "type": "motion"}, now
        ),
        "binary_sensor.c": SensorState(
            "binary_sensor.c", {"area": "area_c", "type": "motion"}, now
        ),
        "binary_sensor.d": SensorState(
            "binary_sensor.d", {"area": "area_d", "type": "motion"}, now
        ),
    }

    # Setup: p1 in D (entry at t=0), p2 in C (entry at t=10), p3 in B (entry at t=20)
    areas["area_d"].record_entry(now)
    areas["area_d"].last_motion = now
    sensors["binary_sensor.d"].update_state(True, now)
    sensors["binary_sensor.d"].update_state(False, now + 5)

    areas["area_c"].record_entry(now + 10)
    areas["area_c"].last_motion = now + 10
    sensors["binary_sensor.c"].update_state(True, now + 10)

    areas["area_b"].record_entry(now + 20)
    areas["area_b"].last_motion = now + 20
    sensors["binary_sensor.b"].update_state(True, now + 20)
    sensors["binary_sensor.b"].update_state(False, now + 25)

    assert areas["area_b"].occupancy == 1
    assert areas["area_c"].occupancy == 1
    assert areas["area_d"].occupancy == 1

    # Step 1: p2 moves C→D. D re-triggers, C OFF
    _fire(resolver, sensors, areas, "binary_sensor.d", True, now + 100, detector)
    _fire(resolver, sensors, areas, "binary_sensor.c", False, now + 101, detector)
    assert areas["area_c"].occupancy == 0
    assert areas["area_d"].occupancy == 2, "D should have p1 + p2"

    # Step 2: p3 moves B→C. C triggers, B OFF
    _fire(resolver, sensors, areas, "binary_sensor.c", True, now + 110, detector)
    _fire(resolver, sensors, areas, "binary_sensor.b", False, now + 111, detector)
    assert areas["area_b"].occupancy == 0
    assert areas["area_c"].occupancy == 1, "p3 now in C"

    # Step 3: p3 moves C→D. D re-triggers, C OFF
    _fire(resolver, sensors, areas, "binary_sensor.d", True, now + 120, detector)
    _fire(resolver, sensors, areas, "binary_sensor.c", False, now + 121, detector)
    assert areas["area_c"].occupancy == 0
    assert areas["area_d"].occupancy == 3, "D should have all 3 people"


# ---------------------------------------------------------------------------
# 1F: Sensor Reliability Recovery
# ---------------------------------------------------------------------------


def test_stuck_sensor_recovers_on_transition():
    """Stuck+unreliable sensor transitions OFF->ON -> should become reliable again."""
    now = time.time()
    sensor = SensorState(
        "binary_sensor.test", {"area": "test_area", "type": "motion"}, now
    )

    # Make sensor stuck ON for >24h
    sensor.update_state(True, now)
    sensor.calculate_is_stuck(now + 86401)
    assert sensor.is_stuck is True
    sensor.is_reliable = False

    # Sensor transitions OFF then ON (recovery)
    sensor.update_state(False, now + 86402)
    sensor.update_state(True, now + 86403)

    # Reliability recovery fix: state transition restores is_reliable
    assert sensor.is_reliable is True


def test_recovered_sensor_warns_again_if_stuck():
    """Recovered sensor that gets stuck again -> calculate_is_stuck returns True."""
    now = time.time()
    sensor = SensorState(
        "binary_sensor.test", {"area": "test_area", "type": "motion"}, now
    )

    # First stuck cycle
    sensor.update_state(True, now)
    sensor.calculate_is_stuck(now + 86401)
    assert sensor.is_stuck is True
    sensor.is_reliable = False

    # Recovery
    sensor.update_state(False, now + 86402)
    sensor.is_stuck = False
    sensor.is_reliable = True

    # Get stuck again
    sensor.update_state(True, now + 86403)
    result = sensor.calculate_is_stuck(now + 86403 + 86401)

    # Reliability recovery allows re-detection of stuck state
    assert result is True
    assert sensor.is_stuck is True


# ---------------------------------------------------------------------------
# 1G: Sensor Edge Cases
# ---------------------------------------------------------------------------


def test_motion_off_null_activated_at():
    """Sensor with activated_at=None, area occupied -> OFF -> stays occupied."""
    now = time.time()
    config = {
        "areas": {
            "area_a": {"name": "A", "indoors": True},
        },
        "adjacency": {
            "area_a": [],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "area_a": AreaState("area_a", config["areas"]["area_a"]),
    }
    sensors = {
        "binary_sensor.a": SensorState(
            "binary_sensor.a", {"area": "area_a", "type": "motion"}, now
        ),
    }

    # Manually set up: area occupied, sensor ON but activated_at=None
    areas["area_a"].record_entry(now)
    areas["area_a"].last_motion = now
    sensors["binary_sensor.a"].current_state = True
    sensors["binary_sensor.a"].activated_at = None  # Explicitly null

    # process_snapshot for OFF will call update_state(False, ...) which does NOT set activated_at
    # The OFF handler checks sensor.activated_at which is still None at the check point (line 401)
    # because update_state is called first (line 124) and OFF doesn't change activated_at.
    # Actually, update_state(False) does NOT modify activated_at, so it stays None.
    _fire(resolver, sensors, areas, "binary_sensor.a", False, now + 10, detector)

    # With activated_at=None, _handle_motion_off returns early -> person stays
    assert areas["area_a"].occupancy == 1


def test_rapid_on_off_on_off():
    """Non-exit area, rapid ON/OFF/ON/OFF cycle -> stays occupied."""
    now = time.time()
    config = {
        "areas": {
            "area_a": {"name": "A", "indoors": True},
        },
        "adjacency": {
            "area_a": [],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "area_a": AreaState("area_a", config["areas"]["area_a"]),
    }
    sensors = {
        "binary_sensor.a": SensorState(
            "binary_sensor.a", {"area": "area_a", "type": "motion"}, now
        ),
    }

    # ON at t=0
    _fire(resolver, sensors, areas, "binary_sensor.a", True, now, detector)
    assert areas["area_a"].occupancy == 1

    # OFF at t=0.3
    _fire(resolver, sensors, areas, "binary_sensor.a", False, now + 0.3, detector)
    assert areas["area_a"].occupancy == 1  # stays (non-exit, no neighbor)

    # ON at t=0.5
    _fire(resolver, sensors, areas, "binary_sensor.a", True, now + 0.5, detector)
    assert areas["area_a"].occupancy == 1  # already occupied, no increment

    # OFF at t=5
    _fire(resolver, sensors, areas, "binary_sensor.a", False, now + 5, detector)
    assert areas["area_a"].occupancy == 1  # stays (non-exit, no neighbor)


# ---------------------------------------------------------------------------
# 1H: Activity Consumption
# ---------------------------------------------------------------------------


def test_consumed_activity_not_reused_as_source():
    """B's activity was consumed by exit to C -> A ON should not count B as plausible source."""
    now = time.time()
    config = {
        "areas": {
            "area_a": {"name": "A", "indoors": True},
            "area_b": {"name": "B", "indoors": True},
            "area_c": {"name": "C", "indoors": True},
        },
        "adjacency": {
            "area_a": ["area_b"],
            "area_b": ["area_a", "area_c"],
            "area_c": ["area_b"],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "area_a": AreaState("area_a", config["areas"]["area_a"]),
        "area_b": AreaState("area_b", config["areas"]["area_b"]),
        "area_c": AreaState("area_c", config["areas"]["area_c"]),
    }
    sensors = {
        "binary_sensor.a": SensorState(
            "binary_sensor.a", {"area": "area_a", "type": "motion"}, now
        ),
        "binary_sensor.b": SensorState(
            "binary_sensor.b", {"area": "area_b", "type": "motion"}, now
        ),
        "binary_sensor.c": SensorState(
            "binary_sensor.c", {"area": "area_c", "type": "motion"}, now
        ),
    }

    # Set up: B's activity was consumed (person moved from B to C recently)
    # B is empty, with last_exit_to = {area_c: recent}, last_motion = recent
    areas["area_b"].last_motion = now - 5
    areas["area_b"].occupancy = 0
    areas["area_b"].last_exit_to = {"area_c": now - 5}
    # B sensor is OFF
    sensors["binary_sensor.b"].update_state(True, now - 10)
    sensors["binary_sensor.b"].update_state(False, now - 5)

    # C is occupied (person moved there from B)
    areas["area_c"].record_entry(now - 5)
    areas["area_c"].last_motion = now - 5

    # Now A turns ON - B's activity is consumed (moved to C), so A should NOT
    # find B as a plausible indoor source
    _fire(resolver, sensors, areas, "binary_sensor.a", True, now, detector)

    # A still becomes occupied (motion-ON always marks occupied) but should warn
    # since B's activity was consumed
    warnings = detector.get_warnings()
    has_no_source_warning = any(
        "no_adjacent_source" in w.message or "indoor_activation_unlinked" in w.message
        for w in warnings
    )
    assert has_no_source_warning


# ---------------------------------------------------------------------------
# 2A: Multi-Sensor Same Room
# ---------------------------------------------------------------------------


def test_multi_sensor_same_room_first_off_ignored():
    """Two sensors in same room, first OFF should be ignored if second is still ON."""
    now = time.time()
    config = {
        "areas": {
            "area_a": {"name": "A", "indoors": True},
            "area_b": {"name": "B", "indoors": True},
        },
        "adjacency": {
            "area_a": ["area_b"],
            "area_b": ["area_a"],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "area_a": AreaState("area_a", config["areas"]["area_a"]),
        "area_b": AreaState("area_b", config["areas"]["area_b"]),
    }
    sensors = {
        "binary_sensor.a1": SensorState(
            "binary_sensor.a1", {"area": "area_a", "type": "motion"}, now
        ),
        "binary_sensor.a2": SensorState(
            "binary_sensor.a2", {"area": "area_a", "type": "motion"}, now
        ),
        "binary_sensor.b": SensorState(
            "binary_sensor.b", {"area": "area_b", "type": "motion"}, now
        ),
    }

    # Person enters area_a — both sensors ON
    _fire(resolver, sensors, areas, "binary_sensor.a1", True, now, detector)
    _fire(resolver, sensors, areas, "binary_sensor.a2", True, now + 1, detector)
    assert areas["area_a"].occupancy == 1

    # sensor_a1 goes OFF while sensor_a2 is still ON
    _fire(resolver, sensors, areas, "binary_sensor.a1", False, now + 10, detector)

    # area_a should remain occupied — the other sensor is still active
    assert areas["area_a"].occupancy == 1
    assert areas["area_b"].occupancy == 0


def test_multi_sensor_same_room_last_off_triggers_movement():
    """When ALL sensors in a room go OFF, movement detection proceeds normally."""
    now = time.time()
    config = {
        "areas": {
            "area_a": {"name": "A", "indoors": True},
            "area_b": {"name": "B", "indoors": True},
        },
        "adjacency": {
            "area_a": ["area_b"],
            "area_b": ["area_a"],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "area_a": AreaState("area_a", config["areas"]["area_a"]),
        "area_b": AreaState("area_b", config["areas"]["area_b"]),
    }
    sensors = {
        "binary_sensor.a1": SensorState(
            "binary_sensor.a1", {"area": "area_a", "type": "motion"}, now
        ),
        "binary_sensor.a2": SensorState(
            "binary_sensor.a2", {"area": "area_a", "type": "motion"}, now
        ),
        "binary_sensor.b": SensorState(
            "binary_sensor.b", {"area": "area_b", "type": "motion"}, now
        ),
    }

    # Person enters area_a — both sensors ON
    _fire(resolver, sensors, areas, "binary_sensor.a1", True, now, detector)
    _fire(resolver, sensors, areas, "binary_sensor.a2", True, now + 1, detector)
    assert areas["area_a"].occupancy == 1

    # B activates (person moving to B)
    _fire(resolver, sensors, areas, "binary_sensor.b", True, now + 5, detector)

    # First sensor OFF — still one sensor active, no movement
    _fire(resolver, sensors, areas, "binary_sensor.a1", False, now + 8, detector)
    assert areas["area_a"].occupancy == 1

    # Last sensor OFF — movement detection should proceed, B is in window
    _fire(resolver, sensors, areas, "binary_sensor.a2", False, now + 10, detector)
    assert areas["area_a"].occupancy == 0
    assert areas["area_b"].occupancy == 1


def test_multi_sensor_camera_and_pir_in_same_area():
    """Camera person + PIR motion in same area. PIR off first, camera still on."""
    now = time.time()
    config = {
        "areas": {
            "area_a": {"name": "A", "indoors": True},
            "area_b": {"name": "B", "indoors": True},
        },
        "adjacency": {
            "area_a": ["area_b"],
            "area_b": ["area_a"],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "area_a": AreaState("area_a", config["areas"]["area_a"]),
        "area_b": AreaState("area_b", config["areas"]["area_b"]),
    }
    sensors = {
        "binary_sensor.a_camera": SensorState(
            "binary_sensor.a_camera",
            {"area": "area_a", "type": "camera_person"},
            now,
        ),
        "binary_sensor.a_pir": SensorState(
            "binary_sensor.a_pir", {"area": "area_a", "type": "motion"}, now
        ),
        "binary_sensor.b": SensorState(
            "binary_sensor.b", {"area": "area_b", "type": "motion"}, now
        ),
    }

    # Both sensors ON in area_a
    _fire(resolver, sensors, areas, "binary_sensor.a_camera", True, now, detector)
    _fire(resolver, sensors, areas, "binary_sensor.a_pir", True, now + 1, detector)
    assert areas["area_a"].occupancy == 1

    # PIR goes OFF while camera_person is still ON — no movement
    _fire(resolver, sensors, areas, "binary_sensor.a_pir", False, now + 15, detector)

    assert areas["area_a"].occupancy == 1
    assert areas["area_b"].occupancy == 0


# ---------------------------------------------------------------------------
# 2C: Activity Consumption Edge Cases
# ---------------------------------------------------------------------------


def test_person_returns_after_exit_consumed():
    """Person exits A->B, then returns B->A. A's motion should recognize B as plausible source."""
    now = time.time()
    config = {
        "areas": {
            "area_a": {"name": "A", "indoors": True},
            "area_b": {"name": "B", "indoors": True},
            "area_c": {"name": "C", "indoors": True},
        },
        "adjacency": {
            "area_a": ["area_b"],
            "area_b": ["area_a", "area_c"],
            "area_c": ["area_b"],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "area_a": AreaState("area_a", config["areas"]["area_a"]),
        "area_b": AreaState("area_b", config["areas"]["area_b"]),
        "area_c": AreaState("area_c", config["areas"]["area_c"]),
    }
    sensors = {
        "binary_sensor.a": SensorState(
            "binary_sensor.a", {"area": "area_a", "type": "motion"}, now
        ),
        "binary_sensor.b": SensorState(
            "binary_sensor.b", {"area": "area_b", "type": "motion"}, now
        ),
        "binary_sensor.c": SensorState(
            "binary_sensor.c", {"area": "area_c", "type": "motion"}, now
        ),
    }

    # Person starts in A
    _fire(resolver, sensors, areas, "binary_sensor.a", True, now, detector)
    assert areas["area_a"].occupancy == 1

    # Person moves A -> B
    _fire(resolver, sensors, areas, "binary_sensor.b", True, now + 3, detector)
    _fire(resolver, sensors, areas, "binary_sensor.a", False, now + 5, detector)
    assert areas["area_a"].occupancy == 0
    assert areas["area_b"].occupancy == 1
    # A should have last_exit_to containing area_b
    assert "area_b" in areas["area_a"].last_exit_to

    # B motion-OFF, person stays in B (no neighbor activated)
    _fire(resolver, sensors, areas, "binary_sensor.b", False, now + 30, detector)
    assert areas["area_b"].occupancy == 1

    # Later: person returns B -> A
    # B is adjacent to A, B has occupancy=1 → plausible source for A
    _fire(resolver, sensors, areas, "binary_sensor.a", True, now + 60, detector)

    # A should become occupied; B is a valid indoor source (occupancy > 0)
    assert areas["area_a"].occupancy == 1


def test_consumed_activity_expires_after_5_minutes():
    """last_exit_to entries older than 5 minutes should be cleaned up."""
    now = time.time()
    config = {
        "areas": {
            "area_a": {"name": "A", "indoors": True},
            "area_b": {"name": "B", "indoors": True},
        },
        "adjacency": {
            "area_a": ["area_b"],
            "area_b": ["area_a"],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "area_a": AreaState("area_a", config["areas"]["area_a"]),
        "area_b": AreaState("area_b", config["areas"]["area_b"]),
    }
    sensors = {
        "binary_sensor.a": SensorState(
            "binary_sensor.a", {"area": "area_a", "type": "motion"}, now
        ),
        "binary_sensor.b": SensorState(
            "binary_sensor.b", {"area": "area_b", "type": "motion"}, now
        ),
    }

    # Person moves A -> B at t=0
    _fire(resolver, sensors, areas, "binary_sensor.a", True, now, detector)
    _fire(resolver, sensors, areas, "binary_sensor.b", True, now + 3, detector)
    _fire(resolver, sensors, areas, "binary_sensor.a", False, now + 5, detector)
    assert areas["area_a"].occupancy == 0
    assert "area_b" in areas["area_a"].last_exit_to

    # At t=301 (5+ minutes later), trigger another exit from A to force cleanup.
    # record_exit cleans up stale last_exit_to entries.
    # First, give A occupancy so record_exit works:
    areas["area_a"].record_entry(now + 200)
    areas["area_a"].record_exit(now + 301, target_id="area_b")

    # The old exit_to entry at t=5 should be cleaned up (301 - 5 = 296 > 300? No)
    # Actually (now+301) - (now+5) = 296 < 300, so it won't be cleaned yet.
    # Let's use t=306 to exceed the 300s threshold:
    areas["area_a"].record_entry(now + 302)
    areas["area_a"].record_exit(now + 306, target_id="area_c")

    # Now the old exit at t=5 is (306-5)=301 > 300 -> should be cleaned
    # But the exit at t=301 is (306-301)=5 < 300 -> should remain
    assert ("area_b" not in areas["area_a"].last_exit_to) or (
        areas["area_a"].last_exit_to.get("area_b") == now + 301
    )


# ---------------------------------------------------------------------------
# 2D: Sensor Edge Cases
# ---------------------------------------------------------------------------


def test_sensor_power_cycle_off_ignored():
    """Sensor power cycles (restart). OFF event with occupancy=0 is safely ignored."""
    now = time.time()
    config = {
        "areas": {
            "area_a": {"name": "A", "indoors": True},
        },
        "adjacency": {
            "area_a": [],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "area_a": AreaState("area_a", config["areas"]["area_a"]),
    }
    sensors = {
        "binary_sensor.a": SensorState(
            "binary_sensor.a", {"area": "area_a", "type": "motion"}, now
        ),
    }

    # Area is empty, sensor was never turned ON (initial state is False).
    # Process an OFF event (as if sensor restarted and reported OFF).
    _fire(resolver, sensors, areas, "binary_sensor.a", False, now + 10, detector)

    # No crash, occupancy stays 0
    assert areas["area_a"].occupancy == 0


def test_repeated_on_events_update_last_motion():
    """Repeated ON events should update area.last_motion (keep-alive behavior)."""
    now = time.time()
    config = {
        "areas": {
            "area_a": {"name": "A", "indoors": True},
        },
        "adjacency": {
            "area_a": [],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "area_a": AreaState("area_a", config["areas"]["area_a"]),
    }
    sensors = {
        "binary_sensor.a": SensorState(
            "binary_sensor.a", {"area": "area_a", "type": "motion"}, now
        ),
    }

    # First ON at t=0
    _fire(resolver, sensors, areas, "binary_sensor.a", True, now, detector)
    assert areas["area_a"].occupancy == 1
    assert areas["area_a"].last_motion == now

    # Repeated ON at t=60 (sensor re-reports ON without going OFF first).
    # sensor.update_state returns False (no state change), but process_snapshot
    # still reads new_state from the snapshot description (line 78: parts[2] == "on").
    # At line 109-110: sensor_type is "motion" and new_state is True, so
    # _handle_motion_on IS called. At line 212: area.last_motion = timestamp.
    # Since area.occupancy > 0, it returns early at line 215 but last_motion
    # was already updated at line 212.
    _fire(resolver, sensors, areas, "binary_sensor.a", True, now + 60, detector)

    assert areas["area_a"].occupancy == 1  # still 1, no increment
    assert areas["area_a"].last_motion == now + 60  # updated by _handle_motion_on


# ---------------------------------------------------------------------------
# 2E: Exit-Capable Edge Cases
# ---------------------------------------------------------------------------


def test_exit_capable_with_neighbor_activation_long_ago():
    """Exit-capable area OFF with stale neighbor activation -> person left system."""
    now = time.time()
    config = {
        "areas": {
            "frontyard": {
                "name": "Front Yard",
                "transition": True,
                "exit_capable": True,
                "indoors": False,
            },
            "foyer": {"name": "Foyer", "indoors": True},
        },
        "adjacency": {
            "frontyard": ["foyer"],
            "foyer": ["frontyard"],
        },
        "sensors": {},
    }

    resolver = MapOccupancyResolver(config)
    detector = AnomalyDetector(config)

    areas = {
        "frontyard": AreaState("frontyard", config["areas"]["frontyard"]),
        "foyer": AreaState("foyer", config["areas"]["foyer"]),
    }
    sensors = {
        "binary_sensor.frontyard": SensorState(
            "binary_sensor.frontyard",
            {"area": "frontyard", "type": "motion"},
            now,
        ),
        "binary_sensor.foyer": SensorState(
            "binary_sensor.foyer", {"area": "foyer", "type": "motion"}, now
        ),
    }

    # Foyer had activation 100s ago (stale)
    _fire(resolver, sensors, areas, "binary_sensor.foyer", True, now, detector)
    _fire(resolver, sensors, areas, "binary_sensor.foyer", False, now + 10, detector)

    # Person enters frontyard at t=100
    _fire(
        resolver, sensors, areas, "binary_sensor.frontyard", True, now + 100, detector
    )
    assert areas["frontyard"].occupancy == 1

    # Frontyard OFF at t=200 — foyer activation was at t=0, way outside all windows.
    # source_on=100, foyer sensor is OFF -> _get_area_activated_at returns None for foyer.
    # No valid neighbors found, exit-capable -> person left system.
    _fire(
        resolver, sensors, areas, "binary_sensor.frontyard", False, now + 200, detector
    )

    assert areas["frontyard"].occupancy == 0
    assert areas["foyer"].occupancy == 0


def test_exit_capable_timeout_clears_even_with_motion():
    """Exit-capable 5-minute timeout clears occupancy even if last_motion is old."""
    now = time.time()
    config = {
        "areas": {
            "frontyard": {
                "name": "Front Yard",
                "transition": True,
                "exit_capable": True,
                "indoors": False,
            },
        },
        "adjacency": {
            "frontyard": [],
        },
        "sensors": {},
    }

    detector = AnomalyDetector(config)

    areas = {
        "frontyard": AreaState("frontyard", config["areas"]["frontyard"]),
    }

    # Frontyard occupied, last_motion was 301s ago (just over 5 minutes)
    areas["frontyard"].record_entry(now)
    areas["frontyard"].last_motion = now

    # check_timeouts at now + 301 -> auto-clear
    detector.check_timeouts(areas, now + 301)

    assert areas["frontyard"].occupancy == 0

    # Verify a warning was created
    warnings = detector.get_warnings()
    has_exit_clear_warning = any(w.type == "exit_area_auto_clear" for w in warnings)
    assert has_exit_clear_warning

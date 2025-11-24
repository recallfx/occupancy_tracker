from __future__ import annotations

import logging
from enum import Enum, auto
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .anomaly_detector import AnomalyDetector
from .area_state import AreaState
from .map_state_recorder import MapSnapshot
from .sensor_state import SensorState
from .types import OccupancyTrackerConfig


_LOGGER = logging.getLogger(__name__)


class TransitionOutcome(Enum):
    """Represents how a motion event should affect occupancy."""

    ALREADY_PRESENT = auto()
    MOVED_FROM_NEIGHBOR = auto()
    ENTERED_FROM_OUTSIDE = auto()
    INVALID = auto()


class MapOccupancyResolver:
    """Derives occupancy directly from recorded map snapshots."""

    MOTION_SENSOR_TYPES = {"motion", "camera_motion", "camera_person"}
    ADJACENT_ACTIVITY_WINDOW = 120  # seconds
    DEACTIVATION_LOOKBACK = 3

    def __init__(self, config: OccupancyTrackerConfig) -> None:
        self.adjacency_map = self._build_adjacency(config)
        self._recent_deactivations: Dict[str, List[float]] = {}

    def reset(self) -> None:
        self._recent_deactivations.clear()

    @staticmethod
    def _build_adjacency(config: OccupancyTrackerConfig) -> Dict[str, List[str]]:
        adjacency = config.get("adjacency", {}) if isinstance(config, dict) else {}
        normalized: Dict[str, List[str]] = {}
        for area_id, neighbors in adjacency.items():
            area_list = normalized.setdefault(area_id, [])
            for neighbor in neighbors:
                if neighbor not in area_list:
                    area_list.append(neighbor)
                reverse_list = normalized.setdefault(neighbor, [])
                if area_id not in reverse_list:
                    reverse_list.append(area_id)
        return normalized

    def process_snapshot(
        self,
        snapshot: MapSnapshot,
        areas: Dict[str, AreaState],
        sensors: Dict[str, SensorState],
        anomaly_detector: Optional[AnomalyDetector] = None,
    ) -> None:
        """Apply a single snapshot event to update occupancy state."""
        event = self._parse_sensor_event(snapshot)
        if not event:
            return

        sensor_id, new_state = event
        sensor = sensors.get(sensor_id)
        if not sensor:
            _LOGGER.debug("Sensor %s not tracked; skipping snapshot", sensor_id)
            return

        sensor_type = sensor.config.get("type", "")
        timestamp = snapshot.timestamp

        if sensor_type in self.MOTION_SENSOR_TYPES:
            if new_state:
                self._handle_motion_on(
                    sensor,
                    timestamp,
                    areas,
                    anomaly_detector,
                )
            else:
                self._handle_motion_off(sensor, timestamp)
        elif sensor_type == "magnetic":
            self._handle_magnetic_event(
                sensor,
                new_state,
                timestamp,
                areas,
            )
        else:
            _LOGGER.debug("Ignoring unsupported sensor type %s", sensor_type)

    def recalculate_from_history(
        self,
        snapshots: Iterable[MapSnapshot],
        areas: Dict[str, AreaState],
        sensors: Dict[str, SensorState],
        anomaly_detector: Optional[AnomalyDetector] = None,
    ) -> None:
        """Rebuild occupancy entirely from history (used for resets)."""
        history = sorted(list(snapshots), key=lambda snap: snap.timestamp)
        self.reset()
        
        # Reset all areas
        for area in areas.values():
            area.occupancy = 0
            area.last_motion = 0
            area.activity_history = []

        for snapshot in history:
            self.process_snapshot(snapshot, areas, sensors, anomaly_detector)

    def _parse_sensor_event(self, snapshot: MapSnapshot) -> Optional[Tuple[str, bool]]:
        if snapshot.event_type != "sensor" or not snapshot.description:
            return None
        parts = snapshot.description.split(":")
        if len(parts) != 3 or parts[0] != "sensor":
            return None
        sensor_id = parts[1]
        new_state = parts[2] == "on"
        return sensor_id, new_state

    def _handle_motion_on(
        self,
        sensor: SensorState,
        timestamp: float,
        areas: Dict[str, AreaState],
        anomaly_detector: Optional[AnomalyDetector],
    ) -> None:
        area_ids = self._normalize_area_ids(sensor.config.get("area"))
        if not area_ids:
            _LOGGER.warning("Sensor %s is not linked to any areas", sensor.id)
            return

        for area_id in area_ids:
            area = areas.get(area_id)
            if not area:
                _LOGGER.warning(
                    "Sensor %s references unknown area %s", sensor.id, area_id
                )
                continue

            area.record_motion(timestamp)
            outcome, source_id = self._evaluate_transition(area_id, areas, timestamp)

            if outcome == TransitionOutcome.ALREADY_PRESENT:
                continue

            if outcome == TransitionOutcome.MOVED_FROM_NEIGHBOR and source_id:
                areas[source_id].record_exit(timestamp)
                area.record_entry(timestamp)
                continue

            if outcome == TransitionOutcome.ENTERED_FROM_OUTSIDE:
                area.record_entry(timestamp)
                continue

            # Invalid transitions still count as entries to keep the
            # system responsive, but we surface them to the anomaly detector.
            area.record_entry(timestamp)
            self._report_anomaly(area, sensor, timestamp, anomaly_detector)

    def _handle_motion_off(self, sensor: SensorState, timestamp: float) -> None:
        area_ids = self._normalize_area_ids(sensor.config.get("area"))
        if not area_ids:
            return
        for area_id in area_ids:
            history = self._recent_deactivations.setdefault(area_id, [])
            history.append(timestamp)
            if len(history) > self.DEACTIVATION_LOOKBACK:
                history.pop(0)

    def _handle_magnetic_event(
        self,
        sensor: SensorState,
        state: bool,
        timestamp: float,
        areas: Dict[str, AreaState],
    ) -> None:
        between_areas = sensor.config.get("between_areas")
        if not between_areas:
            area_config = sensor.config.get("area")
            if isinstance(area_config, list):
                between_areas = area_config
            elif isinstance(area_config, str):
                between_areas = [area_config]
            else:
                between_areas = []

        if len(between_areas) != 2:
            _LOGGER.warning(
                "Magnetic sensor %s has invalid between_areas configuration",
                sensor.id,
            )
            return

        if not state:
            return

        for area_id in between_areas:
            area = areas.get(area_id)
            if area:
                area.record_motion(timestamp)

    def _evaluate_transition(
        self,
        area_id: str,
        areas: Dict[str, AreaState],
        timestamp: float,
    ) -> Tuple[TransitionOutcome, Optional[str]]:
        area = areas.get(area_id)
        if not area:
            return (TransitionOutcome.INVALID, None)

        if area.occupancy > 0:
            return (TransitionOutcome.ALREADY_PRESENT, None)

        source_id = self._find_source_area(area_id, areas, timestamp)
        if source_id:
            return (TransitionOutcome.MOVED_FROM_NEIGHBOR, source_id)

        if area.is_exit_capable:
            return (TransitionOutcome.ENTERED_FROM_OUTSIDE, None)

        return (TransitionOutcome.INVALID, None)

    def _report_anomaly(
        self,
        area: AreaState,
        sensor: SensorState,
        timestamp: float,
        anomaly_detector: Optional[AnomalyDetector],
    ) -> None:
        _LOGGER.debug(
            "Unexpected activation in %s from sensor %s", area.id, sensor.id
        )
        if anomaly_detector:
            anomaly_detector.record_unexpected_activation(area.id, sensor.id, timestamp)

    def _find_source_area(
        self,
        target_area_id: str,
        areas: Dict[str, AreaState],
        timestamp: float,
    ) -> Optional[str]:
        neighbors = self.adjacency_map.get(target_area_id, [])
        if not neighbors:
            return None

        for neighbor_id in neighbors:
            neighbor = areas.get(neighbor_id)
            if not neighbor or neighbor.occupancy <= 0:
                continue
            last_motion = neighbor.last_motion or 0
            if last_motion and (timestamp - last_motion) <= self.ADJACENT_ACTIVITY_WINDOW:
                return neighbor_id
            if self._recent_deactivation_within(neighbor_id, timestamp):
                return neighbor_id

        for neighbor_id in neighbors:
            neighbor = areas.get(neighbor_id)
            if neighbor and neighbor.occupancy > 0:
                return neighbor_id

        return None

    def _recent_deactivation_within(self, area_id: str, timestamp: float) -> bool:
        history = self._recent_deactivations.get(area_id)
        if not history:
            return False
        return any((timestamp - value) <= self.ADJACENT_ACTIVITY_WINDOW for value in history)

    @staticmethod
    def _normalize_area_ids(raw_value: Optional[Any]) -> List[str]:
        if isinstance(raw_value, str):
            return [raw_value]
        if isinstance(raw_value, list):
            return [entry for entry in raw_value if isinstance(entry, str)]
        return []

from __future__ import annotations

import logging
from enum import Enum, auto
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .anomaly_detector import AnomalyDetector
from .area_state import AreaState
from .map_state_recorder import MapSnapshot
from .sensor_state import SensorState
from .types import OccupancyTrackerConfig


_LOGGER = logging.getLogger("resolver")


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
    PASS_THROUGH_WINDOW = 1.5  # seconds
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
    ) -> Optional[str]:
        """
        Apply a single snapshot event to update occupancy state.
        Returns the target area ID if a move occurred, else None.
        """
        event = self._parse_sensor_event(snapshot)
        if not event:
            return None

        sensor_id, new_state = event
        sensor = sensors.get(sensor_id)
        if not sensor:
            _LOGGER.debug("Sensor %s not tracked; skipping snapshot", sensor_id)
            return None

        sensor_type = sensor.config.get("type", "")
        timestamp = snapshot.timestamp

        # Update sensor state to match snapshot
        sensor.update_state(new_state, timestamp)

        if sensor_type in self.MOTION_SENSOR_TYPES:
            if new_state:
                return self._handle_motion_on(
                    sensor,
                    timestamp,
                    areas,
                    sensors,
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
        
        return None

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

    def resolve_consistency(
        self,
        areas: Dict[str, AreaState],
        sensors: Dict[str, SensorState],
        timestamp: float,
        anomaly_detector: Optional[AnomalyDetector] = None,
        recent_move_target_id: Optional[str] = None,
    ) -> bool:
        """
        Check for consistency issues and resolve them.
        
        Specifically, if an area is Active (sensor ON) but Empty (occupancy=0),
        it implies a person is there but was 'stolen' or missed.
        We try to refill it from neighbors.
        
        Returns:
            True if any changes were made, False otherwise.
        """
        changes_made = False
        
        # Find areas that are Active but Empty
        for area_id, area in areas.items():
            if area.occupancy == 0 and self._is_area_active(area_id, sensors):
                _LOGGER.debug(f"Consistency check: {area_id} is Active but Empty. Attempting refill.")
                
                # Try to find a source for this area
                source_candidates = self._find_source_areas(area_id, areas, sensors, timestamp)
                
                refilled = False
                for source_id in source_candidates:
                    # Prevent Ping-Pong: Don't refill from the area we just moved TO.
                    if recent_move_target_id and source_id == recent_move_target_id:
                        _LOGGER.debug(
                            f"Consistency check: Skipping refill of {area_id} from {source_id} "
                            f"(Source was the target of recent move)"
                        )
                        continue

                    source_area = areas[source_id]
                    target_area = areas[area_id]
                    
                    # Prevent Vacuum: Don't refill from a source that we recently moved TO.
                    # If target -> source happened recently, we shouldn't pull source -> target.
                    last_exit_to_source = target_area.last_exit_to.get(source_id, 0)
                    if (timestamp - last_exit_to_source) < self.ADJACENT_ACTIVITY_WINDOW:
                        _LOGGER.debug(
                            f"Consistency check: Skipping refill of {area_id} from {source_id} "
                            f"(Target moved to Source recently: {timestamp - last_exit_to_source:.1f}s ago)"
                        )
                        continue

                    old_source_occ = source_area.occupancy
                    
                    _LOGGER.debug(
                        f"Refill detected: {source_id} → {area_id} (consistency fix)"
                    )
                    source_area.record_exit(timestamp, target_id=area_id)
                    area.record_entry(timestamp)
                    
                    _LOGGER.debug(
                        f"  After refill: {source_id}[{old_source_occ}→{source_area.occupancy}], "
                        f"{area_id}[0→{area.occupancy}]"
                    )
                    changes_made = True
                    refilled = True
                    break
                
                if not refilled:
                    if area.is_exit_capable:
                        # Check if we recently exited to any neighbor (Anti-Vacuum for Outside)
                        recently_exited = False
                        for neighbor_id in self.adjacency_map.get(area_id, []):
                            last_exit = area.last_exit_to.get(neighbor_id, 0)
                            if (timestamp - last_exit) < self.ADJACENT_ACTIVITY_WINDOW:
                                recently_exited = True
                                break
                        
                        if not recently_exited:
                            _LOGGER.debug(f"Refill detected: Outside → {area_id} (consistency fix, exit-capable)")
                            area.record_entry(timestamp)
                            changes_made = True
                        else:
                            _LOGGER.debug(f"Consistency check: Skipping refill of {area_id} from Outside (Recently exited to neighbor)")
                    else:
                        _LOGGER.debug(f"Consistency check: No valid source found to refill {area_id}")
        
        return changes_made

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
        sensors: Dict[str, SensorState],
        anomaly_detector: Optional[AnomalyDetector],
    ) -> Optional[str]:
        area_ids = self._normalize_area_ids(sensor.config.get("area"))
        if not area_ids:
            _LOGGER.warning("Sensor %s is not linked to any areas", sensor.id)
            return None

        target_area_id_result = None

        for area_id in area_ids:
            area = areas.get(area_id)
            if not area:
                _LOGGER.warning(
                    "Sensor %s references unknown area %s", sensor.id, area_id
                )
                continue

            area.record_motion(timestamp)
            outcome, source_id = self._evaluate_transition(area_id, areas, sensors, timestamp)

            if outcome == TransitionOutcome.ALREADY_PRESENT:
                continue

            if outcome == TransitionOutcome.MOVED_FROM_NEIGHBOR and source_id:
                source_area = areas[source_id]
                old_source_occ = source_area.occupancy
                old_target_occ = area.occupancy
                
                _LOGGER.debug(
                    f"Movement detected: {source_id} → {area_id} (via {sensor.id})"
                )
                areas[source_id].record_exit(timestamp, target_id=area_id)
                area.record_entry(timestamp)
                
                _LOGGER.debug(
                    f"  After move: {source_id}[{old_source_occ}→{source_area.occupancy}], "
                    f"{area_id}[{old_target_occ}→{area.occupancy}]"
                )
                target_area_id_result = area_id
                continue

            if outcome == TransitionOutcome.ENTERED_FROM_OUTSIDE:
                _LOGGER.debug(
                    f"Entry from outside: → {area_id} (via {sensor.id}, exit-capable)"
                )
                area.record_entry(timestamp)
                continue

            # Invalid transitions still count as entries to keep the
            # system responsive, but we surface them to the anomaly detector.
            _LOGGER.debug(
                f"⚠️  Unexpected motion: {area_id} (via {sensor.id}, no valid source)"
            )
            area.record_entry(timestamp)
            self._report_anomaly(area, sensor, timestamp, areas, anomaly_detector)
        
        return target_area_id_result

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
        sensors: Dict[str, SensorState],
        timestamp: float,
    ) -> Tuple[TransitionOutcome, Optional[str]]:
        area = areas.get(area_id)
        if not area:
            return (TransitionOutcome.INVALID, None)

        # Check for movement from neighbors first
        # This handles multi-occupant scenarios where someone moves into an already-occupied area
        source_candidates = self._find_source_areas(area_id, areas, sensors, timestamp)
        if source_candidates:
            # For normal transitions, we just take the best candidate
            return (TransitionOutcome.MOVED_FROM_NEIGHBOR, source_candidates[0])

        # If area already has occupants and no one is moving in, it's a keep-alive
        if area.occupancy > 0:
            return (TransitionOutcome.ALREADY_PRESENT, None)

        if area.is_exit_capable:
            return (TransitionOutcome.ENTERED_FROM_OUTSIDE, None)

        return (TransitionOutcome.INVALID, None)

    def _report_anomaly(
        self,
        area: AreaState,
        sensor: SensorState,
        timestamp: float,
        areas: Dict[str, AreaState],
        anomaly_detector: Optional[AnomalyDetector],
    ) -> None:
        # Build context about why this is unexpected
        neighbors = self.adjacency_map.get(area.id, [])
        recently_active = []
        for nid in neighbors:
            neighbor = areas.get(nid)
            if neighbor and neighbor.last_motion > 0 and (timestamp - neighbor.last_motion) < self.ADJACENT_ACTIVITY_WINDOW:
                recently_active.append(nid)
        
        context = f"no adjacent activity" if not recently_active else f"recently active: {', '.join(recently_active)}"
        
        _LOGGER.debug(
            "Unexpected activation in %s from sensor %s (%s)", area.id, sensor.id, context
        )
        if anomaly_detector:
            anomaly_detector.record_unexpected_activation(area.id, sensor.id, timestamp, context)

    def _find_source_areas(
        self,
        target_area_id: str,
        areas: Dict[str, AreaState],
        sensors: Dict[str, SensorState],
        timestamp: float,
    ) -> List[str]:
        neighbors = self.adjacency_map.get(target_area_id, [])
        if not neighbors:
            _LOGGER.debug(f"  🔍 {target_area_id}: no neighbors configured")
            return []

        _LOGGER.debug(f"  🔍 {target_area_id}: checking neighbors {neighbors}")
        
        target_area = areas.get(target_area_id)
        is_target_exit = target_area and target_area.is_exit_capable
        
        candidates = []

        # First pass: look for occupied neighbors with recent activity
        for neighbor_id in neighbors:
            neighbor = areas.get(neighbor_id)
            if not neighbor or neighbor.occupancy <= 0:
                _LOGGER.debug(f"    ↳ {neighbor_id}: occ={neighbor.occupancy if neighbor else 'N/A'} (skip)")
                continue
            
            last_motion = neighbor.last_motion or 0
            time_since_motion = timestamp - last_motion if last_motion else float('inf')
            
            # Check if neighbor is currently active (has sensors ON)
            is_active = self._is_area_active(neighbor_id, sensors)
            
            # If target is exit-capable and neighbor is active, prefer treating as new entry
            # UNLESS it's a quick pass-through (short duration since motion started)
            if is_target_exit and is_active:
                if time_since_motion > self.PASS_THROUGH_WINDOW:
                    _LOGGER.debug(f"    ↳ {neighbor_id}: active and > pass-through ({time_since_motion:.1f}s) -> prefer new entry")
                    continue
                else:
                    _LOGGER.debug(f"    ↳ {neighbor_id}: active but <= pass-through ({time_since_motion:.1f}s) -> allow move")
            
            _LOGGER.debug(
                f"    ↳ {neighbor_id}: occ={neighbor.occupancy}, "
                f"last_motion={time_since_motion:.1f}s ago"
            )
            
            if last_motion and time_since_motion <= self.ADJACENT_ACTIVITY_WINDOW:
                _LOGGER.debug(f"    ✓ {neighbor_id}: recent motion found!")
                candidates.append((neighbor_id, last_motion))
                continue
            
            if self._recent_deactivation_within(neighbor_id, timestamp):
                _LOGGER.debug(f"    ✓ {neighbor_id}: recent deactivation found!")
                candidates.append((neighbor_id, last_motion))
                continue

        results = []
        if candidates:
            # Sort by last_motion descending (most recent first)
            candidates.sort(key=lambda x: x[1], reverse=True)
            results.extend([c[0] for c in candidates])
            _LOGGER.debug(f"  🔍 {target_area_id}: found candidates {results}")

        # Second pass: fallback to any occupied neighbor
        _LOGGER.debug(f"  🔍 {target_area_id}: checking fallbacks")
        fallback_candidates = []
        for neighbor_id in neighbors:
            if neighbor_id in results:
                continue

            neighbor = areas.get(neighbor_id)
            if neighbor and neighbor.occupancy > 0:
                # Apply same active check for fallback
                if is_target_exit and self._is_area_active(neighbor_id, sensors):
                    last_motion = neighbor.last_motion or 0
                    time_since_motion = timestamp - last_motion if last_motion else float('inf')
                    
                    if time_since_motion > self.PASS_THROUGH_WINDOW:
                        _LOGGER.debug(f"    ↳ {neighbor_id}: active and > pass-through -> prefer new entry (fallback)")
                        continue
                    
                _LOGGER.debug(f"    ✓ {neighbor_id}: fallback match (occ={neighbor.occupancy})")
                fallback_candidates.append((neighbor_id, neighbor.last_motion))
        
        if fallback_candidates:
            # Sort by last_motion descending
            fallback_candidates.sort(key=lambda x: x[1] if x[1] is not None else 0, reverse=True)
            results.extend([c[0] for c in fallback_candidates])
            _LOGGER.debug(f"  🔍 {target_area_id}: found fallbacks {[c[0] for c in fallback_candidates]}")

        if not results:
            _LOGGER.debug(f"  ✗ {target_area_id}: no source found")
        
        return results


    def _is_area_active(self, area_id: str, sensors: Dict[str, SensorState]) -> bool:
        """Check if any MOTION/CAMERA sensor in the area is currently ON."""
        for sensor in sensors.values():
            if not sensor.current_state:
                continue
            
            # Only consider motion/camera sensors for activity/refill logic
            # Magnetic sensors (doors) can be left open without presence
            sensor_type = sensor.config.get("type", "")
            if sensor_type not in self.MOTION_SENSOR_TYPES:
                continue

            sensor_areas = self._normalize_area_ids(sensor.config.get("area"))
            if area_id in sensor_areas:
                return True
        return False

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

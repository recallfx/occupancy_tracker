from __future__ import annotations

import logging
from collections import deque
from enum import Enum, auto
from typing import Any, Deque, Dict, Iterable, List, Optional, Set, Tuple

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
    """
    Derives occupancy directly from recorded map snapshots.
    
    CORE PRINCIPLES:
    1. Conservation of people: Users cannot appear or disappear in non-exit-capable areas
    2. Adjacency constraint: Users can only move to adjacent areas with sensor activation
    3. Last-motion priority: Area with most recent motion-off most likely has the person
    
    This means:
    - Total occupancy only changes at exit_capable areas
    - Movement only happens via sensor events in connected areas
    - When motion stops, person is probably still there (they just stopped moving)
    """

    MOTION_SENSOR_TYPES = {"motion", "camera_motion", "camera_person"}
    ADJACENT_ACTIVITY_WINDOW = 120  # seconds
    PASS_THROUGH_WINDOW = 1.5  # seconds - quick pass-through detection
    DEACTIVATION_LOOKBACK = 3
    
    # Motion-off thresholds
    RECENT_ACTIVATION_WINDOW = 5.0  # seconds - for explicit movement detection
    ANTI_BOUNCE_WINDOW = 10.0  # seconds - prevent ping-pong between areas
    MASKED_MOVEMENT_WINDOW = 30.0  # seconds - for masked movement detection
    
    # Source detection thresholds
    # "Stationary" here means: sensor has been continuously ON for a short while.
    # This is used as a *weak* signal to avoid stealing from rooms that are clearly
    # being occupied continuously (e.g. hallway sensor stuck ON while someone else passes).
    STATIONARY_THRESHOLD = 5.0  # seconds

    # Anchor protection:
    # Areas that are occupied and have had continuous motion for a while are treated as "anchors".
    # We avoid taking the last occupant from these areas unless there is no other plausible source.
    ANCHOR_ACTIVE_THRESHOLD = 60.0  # seconds
    MAX_SOURCE_SEARCH_HOPS = 6
    
    # Consistency resolution
    MAX_CONSISTENCY_ITERATIONS = 5  # prevent infinite loops

    def __init__(self, config: OccupancyTrackerConfig) -> None:
        self.adjacency_map = self._build_adjacency(config)
        self._recent_deactivations: Dict[str, List[float]] = {}
        self._area_configs: Dict[str, dict] = config.get("areas", {})

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

    def _parse_sensor_event(self, snapshot: MapSnapshot) -> Optional[Tuple[str, bool]]:
        if snapshot.event_type != "sensor" or not snapshot.description:
            return None
        parts = snapshot.description.split(":")
        if len(parts) != 3 or parts[0] != "sensor":
            return None
        sensor_id = parts[1]
        new_state = parts[2] == "on"
        return sensor_id, new_state

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

        move_target = None
        if sensor_type in self.MOTION_SENSOR_TYPES:
            if new_state:
                move_target = self._handle_motion_on(
                    sensor,
                    timestamp,
                    areas,
                    sensors,
                    anomaly_detector,
                )
            else:
                move_target = self._handle_motion_off(sensor, timestamp, areas, sensors)
        
        elif sensor_type in ("door", "garage_door", "window"):
            move_target = self._handle_magnetic_event(sensor, new_state, timestamp, areas)
        
        # Run consistency resolution after the primary event
        # This handles "Bucket Brigade" moves where one person moving 
        # leaves a room empty that is still active.
        self.resolve_consistency(areas, sensors, timestamp)

        return move_target

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



    def _handle_magnetic_event(
        self,
        sensor: SensorState,
        new_state: bool,
        timestamp: float,
        areas: Dict[str, AreaState],
    ) -> Optional[str]:
        """
        Handle magnetic sensor events (doors/windows).
        
        Primary purpose: Maintaining "Active" paths for recursive search.
        Opening a door triggers `record_motion` on both sides, ensuring
        they remain "Active" (last_motion updated) so `_find_recursive_target`
        can traverse them.
        """
        # We only care about Activity (opening/closing/state change)
        # to keep the path alive.
        
        # Find areas linked to this sensor
        # Some sensors link to 2 areas (like doors between rooms)
        sensor_areas = self._normalize_area_ids(sensor.config.get("area"))
        
        # Also check "between_areas" in config if present (legacy support)
        # But usually we map sensors to areas directly.
        # Let's assume the config "area" list contains the connected rooms.
        
        for area_id in sensor_areas:
            area = areas.get(area_id)
            if area:
                # Update last_motion to keep area active
                # This allows _find_recursive_target to use this node
                area.last_motion = timestamp
                _LOGGER.debug(f"Magnetic event on {sensor.id} kept {area_id} active")
        
        return None



    def _handle_motion_on(
        self,
        sensor: SensorState,
        timestamp: float,
        areas: Dict[str, AreaState],
        sensors: Dict[str, SensorState],
        anomaly_detector: AnomalyDetector,
    ) -> Optional[str]:
        """Handle motion sensor turning ON.
        
        Layer 1 - Motion-ON Logic (Simple):
        If area sees motion, mark it occupied immediately.
        This is the leading activation - the moment we detect presence.
        """
        area_id = sensor.config.get("area")
        if not area_id:
            return None
        
        area = areas.get(area_id)
        if not area:
            return None
        
        # Update last_motion timestamp
        area.last_motion = timestamp

        # If area already occupied, nothing to do
        if area.occupancy > 0:
            _LOGGER.debug(f"Motion-ON in occupied {area_id}: already occupied, no change")
            return None

        # Area is empty - mark it occupied (leading activation detected)
        _LOGGER.debug(f"Motion-ON in {area_id}: marking occupied (leading activation)")
        area.record_entry(timestamp)
        return area_id

    def resolve_consistency(
        self,
        areas: Dict[str, AreaState],
        sensors: Dict[str, SensorState],
        timestamp: float,
    ) -> bool:
        """
        Consistency resolution disabled in activation-window model.
        Movement is determined solely by activation-window checks in _handle_motion_off.
        """
        return False

    def _handle_motion_off(
        self,
        sensor: SensorState,
        timestamp: float,
        areas: Dict[str, AreaState],
        sensors: Dict[str, SensorState],
    ) -> Optional[str]:
        """Handle motion sensor turning OFF.
        
        Layer 2 - Motion-OFF Logic (Activation Window):
        Only mark adjacent areas occupied if they activated AFTER this area's ON.
        
        Window rule: neighbor valid if source_on < neighbor_activated <= timestamp
        - Exclusive start: pre-existing neighbor activations don't count
        - Inclusive end: activations very close to OFF count as movement evidence
        
        If no valid neighbor activation:
        - Person STAYED in source area
        - Source remains occupied
        
        If valid neighbor(s) found:
        - Mark valid neighbors as occupied (ambiguous state)
        - Recursively expand to further areas via active paths (multi-hop)
        - If source is transition area, clear it immediately
        - If source is stay-area, keep it occupied too (both now occupied)
        """
        area_id = sensor.config.get("area")
        if not area_id:
            return None
        
        area = areas.get(area_id)
        if not area or area.occupancy <= 0:
            return None

        # Get the source area's activation time (when its sensor turned ON)
        source_on_time = sensor.activated_at
        if source_on_time is None:
            # No valid activation time recorded; treat as stationary
            _LOGGER.debug(f"Motion-OFF in {area_id}: no activation time, person stays")
            return None

        # Scan adjacent areas for valid activations in (source_on_time, timestamp]
        valid_neighbors = []
        for neighbor_id in self.adjacency_map.get(area_id, []):
            neighbor = areas.get(neighbor_id)
            if not neighbor:
                continue
            
            # Get neighbor's most recent activation time
            neighbor_activated = self._get_area_activated_at(neighbor_id, sensors)
            if neighbor_activated is None:
                continue
            
            # Check if neighbor activated in the window: source_on < neighbor <= off
            if source_on_time < neighbor_activated <= timestamp:
                valid_neighbors.append((neighbor_id, neighbor_activated))

        # Fallback: if no activation-window evidence, check for currently-active neighbors
        # This handles slow movement where person is between rooms and takes longer than window
        if not valid_neighbors:
            for neighbor_id in self.adjacency_map.get(area_id, []):
                neighbor = areas.get(neighbor_id)
                if not neighbor:
                    continue
                
                # If neighbor is currently ON, person likely moved there or is transitioning
                if self._is_area_active(neighbor_id, sensors):
                    neighbor_activated = self._get_area_activated_at(neighbor_id, sensors)
                    if neighbor_activated is not None:
                        valid_neighbors.append((neighbor_id, neighbor_activated))
                        _LOGGER.debug(f"Motion-OFF {area_id}: found active neighbor {neighbor_id} (slow movement)")

        if not valid_neighbors:
            # No evidence of movement - person stayed
            _LOGGER.debug(f"Motion-OFF in {area_id}: no adjacent activation in window, person stays")
            return None

        # Valid neighbor(s) found - expand to all reachable areas via active paths
        # Multi-hop: traverse through currently-active areas to find all possible targets
        visited = {area_id}
        to_mark = set()
        
        # BFS to find all reachable areas through active paths
        queue = [(n_id, n_time) for n_id, n_time in valid_neighbors]
        for neighbor_id, _ in valid_neighbors:
            to_mark.add(neighbor_id)
            visited.add(neighbor_id)
        
        while queue:
            current_id, current_time = queue.pop(0)
            current = areas.get(current_id)
            if not current:
                continue
            
            # Look for further neighbors reachable through active paths
            for next_id in self.adjacency_map.get(current_id, []):
                if next_id in visited:
                    continue
                
                # Only traverse through active areas (motion currently ON)
                if not self._is_area_active(next_id, sensors):
                    continue
                
                # Check if next area activated in window
                next_activated = self._get_area_activated_at(next_id, sensors)
                if next_activated is None or not (source_on_time < next_activated <= timestamp):
                    continue
                
                # Valid multi-hop target
                visited.add(next_id)
                to_mark.add(next_id)
                queue.append((next_id, next_activated))
                _LOGGER.debug(f"Motion-OFF {area_id}: multi-hop to {next_id} via {current_id}")
        
        # Mark all found targets as occupied
        for target_id in to_mark:
            target = areas.get(target_id)
            if target and target.occupancy == 0:
                _LOGGER.debug(f"Motion-OFF {area_id} → {target_id}: marking occupied (multi-hop)")
                target.record_entry(timestamp)

        # Clear source area (person moved to valid neighbor)
        # This applies to both transition AND stay areas when movement evidence exists
        _LOGGER.debug(f"Motion-OFF in {area_id}: clearing (person moved to neighbor)")
        area.occupancy = 0

        # Return the first target for logging
        return list(to_mark)[0] if to_mark else None




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

    def _area_active_since(
        self, area_id: str, sensors: Dict[str, SensorState]
    ) -> Optional[float]:
        """Return the earliest 'ON since' timestamp for currently-ON sensors in area_id."""
        earliest: Optional[float] = None
        for sensor in sensors.values():
            if not sensor.current_state:
                continue
            sensor_type = sensor.config.get("type", "")
            if sensor_type not in self.MOTION_SENSOR_TYPES:
                continue
            sensor_areas = self._normalize_area_ids(sensor.config.get("area"))
            if area_id not in sensor_areas:
                continue
            if earliest is None or sensor.last_changed < earliest:
                earliest = sensor.last_changed
        return earliest

    def _get_area_activated_at(
        self, area_id: str, sensors: Dict[str, SensorState]
    ) -> Optional[float]:
        """Return the most recent activation timestamp for currently-ON sensors in area_id.
        
        Only considers sensors that are currently active (ON state).
        This ensures we only use activation evidence from live/current motion, not stale activations.
        """
        most_recent: Optional[float] = None
        for sensor in sensors.values():
            # Only consider currently-ON sensors
            if not sensor.current_state:
                continue
            
            sensor_type = sensor.config.get("type", "")
            if sensor_type not in self.MOTION_SENSOR_TYPES:
                continue
            sensor_areas = self._normalize_area_ids(sensor.config.get("area"))
            if area_id not in sensor_areas:
                continue
            # Use activated_at (OFF→ON timestamp), not last_changed
            if sensor.activated_at is not None:
                if most_recent is None or sensor.activated_at > most_recent:
                    most_recent = sensor.activated_at
        return most_recent

    def _area_active_duration(
        self, area_id: str, sensors: Dict[str, SensorState], timestamp: float
    ) -> float:
        """Return continuous active duration (seconds) for an area at timestamp."""
        since = self._area_active_since(area_id, sensors)
        if since is None:
            return 0.0
        return max(0.0, timestamp - since)



    @staticmethod
    def _normalize_area_ids(raw_value: Optional[Any]) -> List[str]:
        if isinstance(raw_value, str):
            return [raw_value]
        if isinstance(raw_value, list):
            return [entry for entry in raw_value if isinstance(entry, str)]
        return []

    def validate_state(
        self,
        areas: Dict[str, AreaState],
        sensors: Dict[str, SensorState],
        timestamp: float,
    ) -> List[Dict[str, Any]]:
        """Validate current state (disabled in lean architecture)."""
        return []

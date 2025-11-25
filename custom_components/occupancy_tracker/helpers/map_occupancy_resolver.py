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
    STATIONARY_THRESHOLD = 5.0  # seconds - sensor active this long = stationary
    
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
                return self._handle_motion_off(sensor, timestamp, areas, sensors)
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
        
        The main work is done in motion-off (pessimistic recalculation).
        This is a safety net for edge cases where an area is Active but Empty.
        
        Returns:
            True if any changes were made, False otherwise.
        """
        changes_made = False
        iterations = 0
        areas_refilled_this_pass: set = set()
        
        while iterations < self.MAX_CONSISTENCY_ITERATIONS:
            iterations += 1
            pass_changes = False
            
            # Find areas that are Active but Empty
            for area_id, area in areas.items():
                if area.occupancy == 0 and self._is_area_active(area_id, sensors):
                    # Don't refill the same area twice in one resolution pass
                    if area_id in areas_refilled_this_pass:
                        continue
                    
                    _LOGGER.debug(f"Consistency check: {area_id} is Active but Empty. Attempting refill.")
                    
                    # Try to find a source for this area.
                    # IMPORTANT: Exclude stationary sources - we shouldn't steal from people
                    # who are clearly staying put (sensor active for a while).
                    source_candidates = self._find_source_areas(
                        area_id, areas, sensors, timestamp, exclude_stationary=True
                    )
                    
                    refilled = False
                    for source_id in source_candidates:
                        # Don't refill from areas we've already refilled in this pass
                        if source_id in areas_refilled_this_pass:
                            _LOGGER.debug(
                                f"Consistency check: Skipping refill of {area_id} from {source_id} "
                                f"(Source was already refilled in this pass)"
                            )
                            continue
                        
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
                        areas_refilled_this_pass.add(area_id)
                        
                        _LOGGER.debug(
                            f"  After refill: {source_id}[{old_source_occ}→{source_area.occupancy}], "
                            f"{area_id}[0→{area.occupancy}]"
                        )
                        changes_made = True
                        pass_changes = True
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
                                areas_refilled_this_pass.add(area_id)
                                changes_made = True
                                pass_changes = True
                            else:
                                _LOGGER.debug(f"Consistency check: Skipping refill of {area_id} from Outside (Recently exited to neighbor)")
                        else:
                            # Area is active but empty with no valid source.
                            # Log this as an anomaly but DON'T force-add - let the system
                            # resolve naturally on the next motion-off event.
                            _LOGGER.debug(
                                f"Consistency check: {area_id} is Active but Empty with no source. "
                                f"Will resolve on next sensor event."
                            )
                            if anomaly_detector:
                                anomaly_detector.record_unexpected_activation(
                                    area_id, 
                                    "unknown", 
                                    timestamp, 
                                    "active area became empty (pending resolution)"
                                )
            
            # If no changes in this pass, we're done
            if not pass_changes:
                break
        
        if iterations >= self.MAX_CONSISTENCY_ITERATIONS:
            _LOGGER.warning(f"Consistency check: hit max iterations ({self.MAX_CONSISTENCY_ITERATIONS}), stopping to prevent infinite loop")
        
        return changes_made

    def resolve_consistency_periodic(
        self,
        areas: Dict[str, AreaState],
        sensors: Dict[str, SensorState],
        timestamp: float,
        anomaly_detector: Optional[AnomalyDetector] = None,
    ) -> bool:
        """
        Periodic consistency check - enforces the three core principles.
        
        PRINCIPLES ENFORCED:
        1. Conservation: Total occupancy only changes at exit_capable areas
        2. Adjacency: People can only be in areas reachable via sensor activations
        3. Last-motion priority: Person most likely in area with longest sensor activation
        
        ALGORITHM:
        1. Identify active areas (sensors currently ON)
        2. For each active-but-empty area, check if it's connected to an occupied area
        3. Redistribute occupants based on sensor activation duration
           - If both sensors have been on for a while, each area should have a person
           - Prioritize areas by how long their sensors have been active
        
        Returns True if any changes were made.
        """
        changes_made = False
        
        # Step 1: Build picture of active areas and their sensor durations
        active_areas_info = []
        for area_id, area in areas.items():
            if self._is_area_active(area_id, sensors):
                time_active = timestamp - (area.last_motion or timestamp)
                active_areas_info.append({
                    'id': area_id,
                    'area': area,
                    'occupancy': area.occupancy,
                    'time_active': time_active,
                    'is_exit_capable': area.is_exit_capable,
                })
        
        if not active_areas_info:
            return False
        
        # Step 2: Find active-but-empty areas that need filling
        active_empty = [a for a in active_areas_info if a['occupancy'] == 0]
        
        if not active_empty:
            return False
        
        # Sort empty areas by time_active (longest first - these most likely have someone)
        active_empty.sort(key=lambda x: x['time_active'], reverse=True)
        
        _LOGGER.debug(
            f"Periodic check: {len(active_empty)} active-but-empty areas: "
            f"{[(a['id'], f'{a['time_active']:.1f}s') for a in active_empty]}"
        )
        
        for empty_info in active_empty:
            empty_area_id = empty_info['id']
            empty_area = empty_info['area']
            time_active = empty_info['time_active']
            
            # Only act if sensor has been on long enough (steady state)
            if time_active < self.STATIONARY_THRESHOLD:
                _LOGGER.debug(
                    f"  Periodic skip {empty_area_id}: active only {time_active:.1f}s "
                    f"(need {self.STATIONARY_THRESHOLD}s)"
                )
                continue
            
            # Step 3: Find occupied adjacent areas we could pull from
            neighbors = self.adjacency_map.get(empty_area_id, [])
            best_source = None
            best_source_time = float('inf')  # We want shortest active time (person who just moved)
            
            for neighbor_id in neighbors:
                neighbor = areas.get(neighbor_id)
                if not neighbor or neighbor.occupancy <= 0:
                    continue
                
                neighbor_is_active = self._is_area_active(neighbor_id, sensors)
                neighbor_time_active = timestamp - (neighbor.last_motion or timestamp)
                
                # CASE A: Neighbor is also active AND stationary
                # Both sensors on for a while → two separate people → redistribute
                if neighbor_is_active and neighbor_time_active >= self.STATIONARY_THRESHOLD:
                    if neighbor.occupancy > 1:
                        # Neighbor has multiple people - definitely can spare one
                        best_source = neighbor_id
                        best_source_time = neighbor_time_active
                        break
                    # Single person but both active long time - redistribute
                    _LOGGER.debug(
                        f"  Both stationary: {empty_area_id} ({time_active:.1f}s) and "
                        f"{neighbor_id} ({neighbor_time_active:.1f}s)"
                    )
                    best_source = neighbor_id
                    best_source_time = neighbor_time_active
                    break
                
                # CASE B: Neighbor sensor is OFF, but has occupant
                # This is the classic "person left but we didn't track it" case
                # Use time since their last motion to judge
                if not neighbor_is_active:
                    neighbor_inactive_time = timestamp - (neighbor.last_motion or 0)
                    
                    # If our sensor has been on LONGER than neighbor's been inactive,
                    # it suggests we had motion while they didn't - person might have moved here
                    if time_active > neighbor_inactive_time:
                        _LOGGER.debug(
                            f"  Inactive neighbor: {neighbor_id} (inactive {neighbor_inactive_time:.1f}s), "
                            f"we've been active {time_active:.1f}s - potential source"
                        )
                        if best_source is None or neighbor_inactive_time < best_source_time:
                            best_source = neighbor_id
                            best_source_time = neighbor_inactive_time
            
            if best_source:
                source = areas[best_source]
                old_source_occ = source.occupancy
                
                _LOGGER.debug(
                    f"Periodic redistribution: {best_source} → {empty_area_id} "
                    f"(empty active for {time_active:.1f}s)"
                )
                source.record_exit(timestamp, target_id=empty_area_id)
                empty_area.record_entry(timestamp)
                changes_made = True
                
                _LOGGER.debug(
                    f"  After: {best_source}[{old_source_occ}→{source.occupancy}], "
                    f"{empty_area_id}[0→{empty_area.occupancy}]"
                )
                continue
            
            # Step 4: No adjacent occupied area - check if this is exit_capable
            # Only exit_capable areas can have people "appear" from outside
            if empty_info['is_exit_capable']:
                # Anti-vacuum: Don't add if we recently sent someone to a neighbor
                recently_exited = False
                for neighbor_id in neighbors:
                    last_exit = empty_area.last_exit_to.get(neighbor_id, 0)
                    if (timestamp - last_exit) < self.ADJACENT_ACTIVITY_WINDOW:
                        recently_exited = True
                        _LOGGER.debug(
                            f"  Periodic skip {empty_area_id}: exited to {neighbor_id} "
                            f"{timestamp - last_exit:.1f}s ago"
                        )
                        break
                
                if not recently_exited:
                    _LOGGER.debug(
                        f"Periodic entry from outside: → {empty_area_id} "
                        f"(exit-capable, active for {time_active:.1f}s)"
                    )
                    empty_area.record_entry(timestamp)
                    changes_made = True
            else:
                # Non-exit-capable area with sensor on but no valid source
                # This is a constraint violation - log it
                _LOGGER.debug(
                    f"  ⚠️ {empty_area_id}: active {time_active:.1f}s but no valid source "
                    f"(not exit_capable, no occupied neighbors)"
                )
                if anomaly_detector:
                    anomaly_detector.record_unexpected_activation(
                        empty_area_id,
                        "unknown",
                        timestamp,
                        f"active for {time_active:.1f}s with no valid source"
                    )
        
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

            # INVALID outcome: No valid source found, and area is not exit-capable.
            # This happens when:
            # 1. First motion in the system (no occupants anywhere) - should add person
            # 2. Motion while neighbor's sensor is still active - should wait for evidence
            # 
            # Check if there are any occupants in the system
            total_occupants = sum(a.occupancy for a in areas.values())
            if total_occupants == 0:
                # No occupants anywhere - someone just appeared, add them
                _LOGGER.debug(
                    f"First occupant detected: → {area_id} (via {sensor.id}, bootstrapping)"
                )
                area.record_entry(timestamp)
                self._report_anomaly(area, sensor, timestamp, areas, anomaly_detector)
            else:
                # There are occupants elsewhere. Don't add - wait for motion-off to resolve.
                _LOGGER.debug(
                    f"⚠️  Unexpected motion: {area_id} (via {sensor.id}, waiting for evidence)"
                )
                self._report_anomaly(area, sensor, timestamp, areas, anomaly_detector)
        
        return target_area_id_result

    def _handle_motion_off(
        self,
        sensor: SensorState,
        timestamp: float,
        areas: Dict[str, AreaState],
        sensors: Dict[str, SensorState],
    ) -> Optional[str]:
        """
        Handle motion sensor deactivation - PRINCIPLE: Person stays where they are.
        
        CORE PRINCIPLE: When motion stops, person is most likely STILL THERE.
        They just stopped moving - that's not evidence they left.
        
        We move a person on motion-off when we have evidence:
        1. An adjacent area's sensor turned ON VERY RECENTLY (within 5s) 
           → explicit movement detected
        2. An adjacent area's sensor is already ON AND already has occupants
           → masked movement (person walked through to join them)
        
        Case 2 handles masked movement but ONLY when the target is occupied.
        If the target is empty but active, it suggests two separate people -
        let the periodic check handle that redistribution.
        
        Returns the target area ID if a move was detected, else None.
        """
        area_ids = self._normalize_area_ids(sensor.config.get("area"))
        if not area_ids:
            return None
        
        target_area_id_result = None
        
        for area_id in area_ids:
            # Record deactivation for history
            history = self._recent_deactivations.setdefault(area_id, [])
            history.append(timestamp)
            if len(history) > self.DEACTIVATION_LOOKBACK:
                history.pop(0)
            
            area = areas.get(area_id)
            if not area or area.occupancy <= 0:
                continue
            
            # Check if this area is still active (another sensor might still be ON)
            if self._is_area_active(area_id, sensors):
                # Area still has an active sensor - person is definitely still here
                _LOGGER.debug(
                    f"Motion-off {area_id}: still has active sensor, person stays"
                )
                continue
            
            # This area is now INACTIVE but OCCUPIED.
            # Look for neighbor evidence of movement.
            neighbors = self.adjacency_map.get(area_id, [])
            best_target = None
            best_target_time = 0
            masked_target = None  # For masked movement to OCCUPIED areas
            
            for neighbor_id in neighbors:
                neighbor = areas.get(neighbor_id)
                if not neighbor:
                    continue
                
                # Anti-bounce: Check if we recently came FROM this neighbor
                last_came_from = neighbor.last_exit_to.get(area_id, 0)
                if (timestamp - last_came_from) < self.ANTI_BOUNCE_WINDOW:
                    _LOGGER.debug(
                        f"  Motion-off skip {area_id} → {neighbor_id}: "
                        f"came from there {timestamp - last_came_from:.1f}s ago (anti-bounce)"
                    )
                    continue
                
                # Is the neighbor currently active (motion sensor ON)?
                if not self._is_area_active(neighbor_id, sensors):
                    continue
                
                neighbor_motion = neighbor.last_motion or 0
                time_since_neighbor_motion = timestamp - neighbor_motion
                
                # CASE 1: Recent activation = strong evidence of movement
                if time_since_neighbor_motion <= self.RECENT_ACTIVATION_WINDOW:
                    if neighbor_motion > best_target_time:
                        best_target = neighbor_id
                        best_target_time = neighbor_motion
                        _LOGGER.debug(
                            f"  Motion-off candidate {area_id} → {neighbor_id}: "
                            f"recent activation {time_since_neighbor_motion:.1f}s ago"
                        )
                # CASE 2: Masked movement - sensor already ON AND target is OCCUPIED
                # This handles: Person walks through an area where someone is already present,
                # sensor stays on the whole time, so we don't get a new activation event.
                elif (time_since_neighbor_motion <= self.MASKED_MOVEMENT_WINDOW and 
                      neighbor.occupancy > 0):
                    _LOGGER.debug(
                        f"  Motion-off masked candidate {area_id} → {neighbor_id}: "
                        f"neighbor active for {time_since_neighbor_motion:.1f}s, "
                        f"already has {neighbor.occupancy} occupant(s)"
                    )
                    if masked_target is None:
                        masked_target = neighbor_id
                else:
                    # Neighbor is active but:
                    # - Not recent (>5s ago)
                    # - Not occupied (empty area with sensor on)
                    # This looks like a second person in another room.
                    # Don't move - let periodic consistency handle redistribution.
                    _LOGGER.debug(
                        f"  Motion-off skip {area_id} → {neighbor_id}: "
                        f"activated {time_since_neighbor_motion:.1f}s ago, occ={neighbor.occupancy} "
                        f"(defer to periodic check)"
                    )
            
            # Prefer explicit recent activation, fall back to masked movement
            chosen_target = best_target or masked_target
            
            if chosen_target:
                neighbor = areas[chosen_target]
                old_source_occ = area.occupancy
                old_target_occ = neighbor.occupancy
                
                move_type = "recent activation" if best_target else "masked movement"
                _LOGGER.debug(
                    f"Motion-off move ({move_type}): {area_id} → {chosen_target} "
                    f"(source inactive, target active+occupied)"
                )
                area.record_exit(timestamp, target_id=chosen_target)
                neighbor.record_entry(timestamp)
                
                _LOGGER.debug(
                    f"  After move: {area_id}[{old_source_occ}→{area.occupancy}], "
                    f"{chosen_target}[{old_target_occ}→{neighbor.occupancy}]"
                )
                target_area_id_result = chosen_target
            else:
                # No recent neighbor activation = no evidence of movement
                # PRINCIPLE: Person stays in this area (they just stopped moving)
                _LOGGER.debug(
                    f"Motion-off {area_id}: no evidence of movement, person STAYS"
                )
        
        return target_area_id_result

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

        # Check for movement from neighbors
        source_candidates = self._find_source_areas(area_id, areas, sensors, timestamp)
        
        # For exit-capable areas (doors to outside), we need evidence of movement:
        # - If source is ACTIVE and passing through quickly → someone is exiting → movement
        # - Otherwise → favor new entry from outside
        #
        # The key insight: an exit-capable area like "entrance" can have people
        # both entering and exiting. If someone inside is actively passing through,
        # they're exiting. Otherwise, it's likely someone new entering.
        
        if source_candidates and area.is_exit_capable:
            source_id = source_candidates[0]
            source_area = areas.get(source_id)
            if source_area:
                source_is_active = self._is_area_active(source_id, sensors)
                time_since_source_motion = timestamp - (source_area.last_motion or 0)
                
                # If source just activated (pass-through), this is an exit
                if source_is_active and time_since_source_motion <= self.PASS_THROUGH_WINDOW:
                    _LOGGER.debug(
                        f"Exit-capable {area_id}: source {source_id} just activated "
                        f"{time_since_source_motion:.1f}s ago - treating as exit"
                    )
                    return (TransitionOutcome.MOVED_FROM_NEIGHBOR, source_id)
                
                # For all other cases (source active but stationary, or source inactive),
                # favor new entry at exit-capable areas
                _LOGGER.debug(
                    f"Exit-capable {area_id}: source {source_id} "
                    f"(active={source_is_active}, motion {time_since_source_motion:.1f}s ago) "
                    f"- treating as new entry"
                )
                return (TransitionOutcome.ENTERED_FROM_OUTSIDE, None)
        
        if source_candidates:
            # For non-exit-capable areas, use movement
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
        exclude_stationary: bool = False,
    ) -> List[str]:
        """
        Find areas that could be the source of movement to target_area_id.
        
        Called on motion-ON (OPTIMISTIC tracking):
        - We assume someone moved here from an occupied neighbor
        - Sort candidates by recency to prefer likely sources
        - For stationary detection (active sensor for a while), deprioritize
        
        Args:
            exclude_stationary: If True, don't return stationary candidates at all.
                               Used by consistency resolution to avoid stealing from
                               people who are clearly staying put.
        
        Returns list of candidate area IDs, sorted by recency.
        """
        neighbors = self.adjacency_map.get(target_area_id, [])
        if not neighbors:
            _LOGGER.debug(f"  🔍 {target_area_id}: no neighbors configured")
            return []

        _LOGGER.debug(f"  🔍 {target_area_id}: checking neighbors {neighbors}")
        
        candidates = []
        stationary_candidates = []

        for neighbor_id in neighbors:
            neighbor = areas.get(neighbor_id)
            if not neighbor or neighbor.occupancy <= 0:
                _LOGGER.debug(f"    ↳ {neighbor_id}: occ={neighbor.occupancy if neighbor else 'N/A'} (skip)")
                continue
            
            last_motion = neighbor.last_motion or 0
            time_since_motion = timestamp - last_motion if last_motion else float('inf')
            
            # Check if neighbor is currently active (has sensors ON)
            is_active = self._is_area_active(neighbor_id, sensors)
            
            # If active AND sensor has been on for a while, they're stationary
            # Don't steal from stationary sources unless no other option
            if is_active and time_since_motion > self.STATIONARY_THRESHOLD:
                _LOGGER.debug(
                    f"    ⚑ {neighbor_id}: occ={neighbor.occupancy}, stationary "
                    f"(active for {time_since_motion:.1f}s)"
                )
                if not exclude_stationary:
                    stationary_candidates.append((neighbor_id, last_motion))
                continue
            
            # Good candidate: either sensor is active (recently), or 
            # sensor is OFF (person just stopped moving and we're following)
            _LOGGER.debug(
                f"    ✓ {neighbor_id}: occ={neighbor.occupancy}, "
                f"active={is_active}, last_motion={time_since_motion:.1f}s ago"
            )
            candidates.append((neighbor_id, last_motion))

        # Sort by last_motion descending (most recent first)
        if candidates:
            candidates.sort(key=lambda x: x[1] if x[1] else 0, reverse=True)
            result = [c[0] for c in candidates]
            _LOGGER.debug(f"  🔍 {target_area_id}: found candidates {result}")
            
            # Add stationary as lower priority fallbacks (if not excluded)
            if stationary_candidates:
                stationary_candidates.sort(key=lambda x: x[1] if x[1] else 0, reverse=True)
                for sc in stationary_candidates:
                    if sc[0] not in result:
                        result.append(sc[0])
            return result
        
        # Only stationary candidates available
        if stationary_candidates:
            stationary_candidates.sort(key=lambda x: x[1] if x[1] else 0, reverse=True)
            result = [c[0] for c in stationary_candidates]
            _LOGGER.debug(f"  🔍 {target_area_id}: found stationary candidates {result}")
            return result

        _LOGGER.debug(f"  ✗ {target_area_id}: no source found")
        return []


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

    def validate_state(
        self,
        areas: Dict[str, AreaState],
        sensors: Dict[str, SensorState],
        timestamp: float,
    ) -> List[Dict[str, Any]]:
        """
        Validate current state against the three core principles.
        
        Returns a list of violations found, each as a dict with:
        - principle: which principle was violated (1, 2, or 3)
        - description: human-readable description
        - area_id: affected area
        - severity: 'warning' or 'error'
        
        Principles:
        1. Conservation: occupancy only changes at exit_capable areas
        2. Adjacency: people can only be in reachable areas
        3. Last-motion: area with sensor on should have person if occupied neighbor has none
        """
        violations = []
        
        # Principle 3: Active areas should have occupants assigned
        # If an area has sensor ON and is adjacent to an occupied area,
        # but has no occupant itself, this is suspicious
        for area_id, area in areas.items():
            is_active = self._is_area_active(area_id, sensors)
            time_active = timestamp - (area.last_motion or timestamp)
            
            if is_active and area.occupancy == 0 and time_active > self.STATIONARY_THRESHOLD:
                # Check if adjacent to occupied area
                neighbors = self.adjacency_map.get(area_id, [])
                occupied_neighbors = [
                    nid for nid in neighbors 
                    if areas.get(nid) and areas[nid].occupancy > 0
                ]
                
                if occupied_neighbors:
                    violations.append({
                        'principle': 3,
                        'description': (
                            f"Area {area_id} has sensor active for {time_active:.1f}s "
                            f"but no occupant, while neighbors {occupied_neighbors} are occupied"
                        ),
                        'area_id': area_id,
                        'severity': 'warning',
                    })
                elif not area.is_exit_capable:
                    # Non-exit-capable with no occupied neighbors
                    violations.append({
                        'principle': 1,
                        'description': (
                            f"Area {area_id} has sensor active but no valid source "
                            f"(not exit_capable, no occupied neighbors)"
                        ),
                        'area_id': area_id,
                        'severity': 'error',
                    })
        
        # Principle 2: Check if any occupied area is "stranded" (no path from exit)
        # Build reachability from exit_capable areas
        exit_areas = [aid for aid, a in areas.items() if a.is_exit_capable]
        reachable = set(exit_areas)
        frontier = list(exit_areas)
        
        while frontier:
            current = frontier.pop()
            for neighbor_id in self.adjacency_map.get(current, []):
                if neighbor_id not in reachable:
                    reachable.add(neighbor_id)
                    frontier.append(neighbor_id)
        
        for area_id, area in areas.items():
            if area.occupancy > 0 and area_id not in reachable:
                violations.append({
                    'principle': 2,
                    'description': (
                        f"Area {area_id} has {area.occupancy} occupant(s) but is not "
                        f"reachable from any exit_capable area"
                    ),
                    'area_id': area_id,
                    'severity': 'error',
                })
        
        return violations

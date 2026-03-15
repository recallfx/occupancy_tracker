from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional, Tuple

from .anomaly_detector import AnomalyDetector
from .area_state import AreaState
from .constants import MAGNETIC_SENSOR_TYPES, MOTION_SENSOR_TYPES, normalize_area_ids
from .map_state_recorder import MapSnapshot
from .sensor_state import SensorState
from .types import OccupancyTrackerConfig


_LOGGER = logging.getLogger("resolver")


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

    ADJACENT_ACTIVITY_WINDOW = 60  # seconds

    # Motion-off thresholds
    RECENT_ACTIVATION_WINDOW = 5.0  # seconds - for explicit movement detection
    MASKED_MOVEMENT_WINDOW = 30.0  # seconds - for masked movement detection
    OUTDOOR_INTRUSION_WINDOW = 300.0  # seconds - outdoor-to-indoor allowance window

    def __init__(self, config: OccupancyTrackerConfig) -> None:
        self.adjacency_map = self._build_adjacency(config)

    def reset(self) -> None:
        pass

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

        # NOTE: Sensor state is updated by the caller (Coordinator / SensorEventHelper)
        # before calling process_snapshot. The resolver only reads sensor state, it does
        # not own sensor state updates.

        move_target = None
        if sensor_type in MOTION_SENSOR_TYPES:
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

        elif sensor_type in MAGNETIC_SENSOR_TYPES:
            move_target = self._handle_magnetic_event(
                sensor, new_state, timestamp, areas
            )

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
            # Update sensor state before processing (mirrors coordinator behavior)
            event = self._parse_sensor_event(snapshot)
            if event:
                sensor_id, new_state = event
                sensor = sensors.get(sensor_id)
                if sensor:
                    sensor.update_state(new_state, snapshot.timestamp)
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
        sensor_areas = normalize_area_ids(sensor.config.get("area"))

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
            _LOGGER.debug(
                f"Motion-ON in occupied {area_id}: already occupied, no change"
            )
            return None

        # Detect unexpected motion when no adjacent source exists
        plausible_source = False
        indoor_source = False
        recent_outdoor_activity = False
        has_outdoor_neighbor = False
        for neighbor_id in self.adjacency_map.get(area_id, []):
            neighbor = areas.get(neighbor_id)
            if not neighbor:
                continue

            neighbor_active = self._is_area_active(neighbor_id, sensors)

            # Check if neighbor was recently active (even if now OFF)
            neighbor_recently_active = (
                timestamp - neighbor.last_motion
            ) <= self.ADJACENT_ACTIVITY_WINDOW

            # If neighbor was recently active but moved to a DIFFERENT area,
            # then its activity is "consumed" and shouldn't justify this area.
            if (
                neighbor_recently_active
                and neighbor.occupancy == 0
                and not neighbor_active
            ):
                # If it moved to THIS area, it's definitely plausible
                if area_id in neighbor.last_exit_to:
                    pass
                elif neighbor.last_exit_to:
                    # It moved elsewhere - check if that move is still "fresh"
                    # If the move happened recently, this neighbor's activity is accounted for.
                    for target_id, exit_ts in neighbor.last_exit_to.items():
                        if (timestamp - exit_ts) <= self.ADJACENT_ACTIVITY_WINDOW:
                            neighbor_recently_active = False
                            break

            # Indoors neighbors with occupancy or active motion are plausible sources
            if neighbor.is_indoors:
                if (
                    neighbor.occupancy > 0
                    or neighbor_active
                    or neighbor_recently_active
                ):
                    plausible_source = True
                    indoor_source = True
                    break

            # Outdoor neighbors are only plausible if already occupied (someone known outside)
            if not neighbor.is_indoors:
                has_outdoor_neighbor = True
                if neighbor.occupancy > 0:
                    plausible_source = True
                    # keep searching to see if an indoor source exists too

            # Track recent outdoor activation to flag potential intrusion
            if not neighbor.is_indoors:
                if (timestamp - neighbor.last_motion) <= self.OUTDOOR_INTRUSION_WINDOW:
                    recent_outdoor_activity = True

        # Door/garage/window activity can legitimize outside → inside entry
        recent_magnetic = False
        for sensor_state in sensors.values():
            sensor_type = sensor_state.config.get("type", "")
            if sensor_type not in MAGNETIC_SENSOR_TYPES:
                continue
            sensor_areas = normalize_area_ids(sensor_state.config.get("area"))
            if area_id not in sensor_areas:
                continue
            if sensor_state.last_changed and sensor_state.last_changed >= (
                timestamp - self.OUTDOOR_INTRUSION_WINDOW
            ):
                recent_magnetic = True
                break

        # If indoor area has no plausible source and no recent outside/magnetic evidence, treat as anomaly and ignore entry
        if (
            area.is_indoors
            and area.occupancy == 0
            and not indoor_source
            and not recent_outdoor_activity
            and not recent_magnetic
            and has_outdoor_neighbor
        ):
            if anomaly_detector:
                anomaly_detector.record_unexpected_activation(
                    area_id,
                    sensor.id,
                    timestamp,
                    context="indoor_activation_unlinked",
                )
            _LOGGER.debug(f"Motion-ON in {area_id}: ignored unlinked indoor activation")
            return None

        if anomaly_detector and not area.is_exit_capable and not recent_magnetic:
            context = None
            if area.is_indoors and recent_outdoor_activity and not indoor_source:
                context = "intrusion_outside_adjacent"
            elif not plausible_source:
                context = "no_adjacent_source"

            if context:
                anomaly_detector.record_unexpected_activation(
                    area_id,
                    sensor.id,
                    timestamp,
                    context=context,
                )

        # Area is empty - mark it occupied (leading activation detected)
        _LOGGER.debug(f"Motion-ON in {area_id}: marking occupied (leading activation)")
        area.record_entry(timestamp)
        return area_id

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
        - Person STAYED in source area (source remains occupied)
        - Exit-capable areas clear immediately (person left the system)

        If valid neighbor(s) found:
        - Mark valid neighbors as occupied via BFS through active paths
        - Decrement source by 1 (record_exit)
        """
        area_id = sensor.config.get("area")
        if not area_id:
            return None

        area = areas.get(area_id)
        if not area or area.occupancy <= 0:
            return None

        # If other motion sensors in this area are still ON, skip movement detection.
        # The area is still actively detecting motion — don't try to move the person.
        for other_sensor in sensors.values():
            if other_sensor.id == sensor.id:
                continue
            if not other_sensor.current_state:
                continue
            other_type = other_sensor.config.get("type", "")
            if other_type not in MOTION_SENSOR_TYPES:
                continue
            other_areas = normalize_area_ids(other_sensor.config.get("area"))
            if area_id in other_areas:
                _LOGGER.debug(
                    f"Motion-OFF in {area_id}: other sensor {other_sensor.id} still active, skipping"
                )
                area.last_motion = timestamp
                return None

        # Update last_motion on deactivation too
        area.last_motion = timestamp

        # Get the source area's activation time (when its sensor turned ON)
        source_on_time = sensor.activated_at
        if source_on_time is None:
            # No valid activation time recorded; treat as stationary
            _LOGGER.debug(f"Motion-OFF in {area_id}: no activation time, person stays")
            return None

        # Helper: decide if a neighbor activation is fresh enough to count as movement evidence
        # We accept either: (a) activation very close to the OFF timestamp, or
        # (b) activation that happened shortly after the source turned ON (common with long sensor timeouts).
        # CRITICAL: neighbor must have activated AFTER source turned ON. A negative delta
        # (neighbor activated before source) must never be treated as movement evidence.
        def _activation_matches_window(neighbor_activated: float) -> bool:
            if neighbor_activated <= source_on_time:
                return False
            if neighbor_activated >= (timestamp - self.RECENT_ACTIVATION_WINDOW):
                return True
            if (neighbor_activated - source_on_time) <= self.MASKED_MOVEMENT_WINDOW:
                return True
            return False

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
            if (
                source_on_time < neighbor_activated <= timestamp
                and _activation_matches_window(neighbor_activated)
            ):
                valid_neighbors.append((neighbor_id, neighbor_activated))

        # Fallback: if no activation-window evidence, check for currently-active neighbors
        # This handles slow movement where person is between rooms and takes longer than window
        if not valid_neighbors:
            for neighbor_id in self.adjacency_map.get(area_id, []):
                neighbor = areas.get(neighbor_id)
                if not neighbor:
                    continue

                # If neighbor is currently ON and occupied, person likely moved or is transitioning
                if neighbor.occupancy > 0 and self._is_area_active(
                    neighbor_id, sensors
                ):
                    neighbor_activated = self._get_area_activated_at(
                        neighbor_id, sensors
                    )
                    if neighbor_activated is not None and _activation_matches_window(
                        neighbor_activated
                    ):
                        valid_neighbors.append((neighbor_id, neighbor_activated))
                        _LOGGER.debug(
                            f"Motion-OFF {area_id}: found active neighbor {neighbor_id} (slow movement)"
                        )

        if not valid_neighbors:
            # If area is exit-capable and motion stops without a neighbor activation,
            # assume the person left the system entirely.
            if area.is_exit_capable:
                _LOGGER.debug(
                    f"Motion-OFF in exit-capable {area_id}: clearing (person left system)"
                )
                area.clear_occupancy(timestamp, target_id="outside")
                return area_id

            # No evidence of movement - person stayed
            _LOGGER.debug(
                f"Motion-OFF in {area_id}: no adjacent activation in window, person stays"
            )
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
                if next_activated is None or not (
                    source_on_time < next_activated <= timestamp
                ):
                    continue

                # Temporal ordering: next hop must have activated after current hop
                if next_activated < current_time:
                    continue

                # Valid multi-hop target
                visited.add(next_id)
                to_mark.add(next_id)
                queue.append((next_id, next_activated))
                _LOGGER.debug(
                    f"Motion-OFF {area_id}: multi-hop to {next_id} via {current_id}"
                )

        # Mark all found targets as occupied
        primary_target = None
        for target_id in to_mark:
            target = areas.get(target_id)
            if target:
                if target.occupancy == 0:
                    _LOGGER.debug(
                        f"Motion-OFF {area_id} → {target_id}: marking occupied (multi-hop)"
                    )
                    target.record_entry(timestamp)
                else:
                    # Target already occupied — check if it was pre-occupied before
                    # this movement chain started. If so, a NEW person is arriving
                    # (motion-ON didn't increment because area was already occupied).
                    target_was_preoccupied = False
                    found_entry = False
                    for ts, evt in reversed(target.activity_history):
                        if evt == "entry":
                            target_was_preoccupied = ts < source_on_time
                            found_entry = True
                            break
                    # If history was truncated and no entry found, assume
                    # pre-occupied (occupancy > 0 with no visible entry means
                    # the entry was evicted from the bounded history).
                    if not found_entry and target.occupancy > 0:
                        target_was_preoccupied = True
                    if target_was_preoccupied:
                        _LOGGER.debug(
                            f"Motion-OFF {area_id} → {target_id}: incrementing "
                            f"(pre-occupied, new person arriving)"
                        )
                        target.record_entry(timestamp)
                if primary_target is None:
                    primary_target = target_id

        if to_mark:
            _LOGGER.debug(
                f"Motion-OFF in {area_id}: clearing (person moved to neighbor)"
            )
            # Record all targets in last_exit_to to ensure activity is consumed for all of them
            targets = list(to_mark)
            # Use record_exit (decrement by 1) for movement to neighbor, even for
            # exit-capable areas. clear_occupancy (zero out) is only for when
            # the person leaves the system entirely (no valid neighbor found).
            area.record_exit(timestamp, target_id=targets)

        # Return the first target for logging
        return primary_target

    def _is_area_active(self, area_id: str, sensors: Dict[str, SensorState]) -> bool:
        """Check if any MOTION/CAMERA sensor in the area is currently ON."""
        for sensor in sensors.values():
            if not sensor.current_state:
                continue

            # Only consider motion/camera sensors for activity/refill logic
            # Magnetic sensors (doors) can be left open without presence
            sensor_type = sensor.config.get("type", "")
            if sensor_type not in MOTION_SENSOR_TYPES:
                continue

            sensor_areas = normalize_area_ids(sensor.config.get("area"))
            if area_id in sensor_areas:
                return True
        return False

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
            if sensor_type not in MOTION_SENSOR_TYPES:
                continue
            sensor_areas = normalize_area_ids(sensor.config.get("area"))
            if area_id not in sensor_areas:
                continue
            # Use activated_at (OFF→ON timestamp), not last_changed
            if sensor.activated_at is not None:
                if most_recent is None or sensor.activated_at > most_recent:
                    most_recent = sensor.activated_at
        return most_recent

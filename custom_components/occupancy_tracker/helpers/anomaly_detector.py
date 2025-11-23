import logging
from collections import deque
from typing import Dict, List, Optional, Set

from .area_state import AreaState
from .sensor_state import SensorState
from .warning import Warning
from .types import OccupancyTrackerConfig

# Configure logger
logger = logging.getLogger(__name__)


class AnomalyDetector:
    """Detects anomalies in sensor readings and occupancy patterns."""

    def __init__(self, config: OccupancyTrackerConfig):
        self.config = config
        self.warnings: List[Warning] = []
        self.recent_motion_window = 120  # 2 minutes
        self.motion_timeout = 24 * 3600  # 24 hours
        self.extended_occupancy_threshold = 12 * 3600  # 12 hours
        self.adjacency_map = self._build_adjacency(config)

    def _build_adjacency(self, config: OccupancyTrackerConfig) -> Dict[str, List[str]]:
        adjacency_config = config.get("adjacency", {}) if isinstance(config, dict) else {}
        adjacency_map: Dict[str, Set[str]] = {}
        for area_id, neighbors in adjacency_config.items():
            area_set = adjacency_map.setdefault(area_id, set())
            for neighbor_id in neighbors:
                area_set.add(neighbor_id)
                adjacency_map.setdefault(neighbor_id, set()).add(area_id)
        return {area_id: sorted(list(neighbors)) for area_id, neighbors in adjacency_map.items()}

    def check_for_stuck_sensors(
        self,
        sensors: Dict[str, SensorState],
        areas: Dict[str, AreaState],
        triggered_sensor_id: str,
    ) -> None:
        """Check for stuck sensors when a sensor is triggered."""
        triggered_sensor = sensors[triggered_sensor_id]
        area_config = triggered_sensor.config.get("area")

        if not area_config:
            return
            
        # We don't need to check if area exists here, as we just want to trigger the check
        # The actual check iterates over all sensors

        # Update adjacent area motion records for all sensors in adjacent areas
        # This logic is complex with bridging sensors, and the "adjacent motion implies stuck"
        # logic is being removed, so we can simplify this.
        # We only need to check for "Stuck ON" (timeout) which doesn't require adjacency info.

        # Check if sensors are stuck
        for sensor_id, sensor in sensors.items():
            # Calculate if stuck (only checks for long active duration now)
            is_stuck = sensor.calculate_is_stuck(
                False, triggered_sensor.last_update_time
            )

            if is_stuck and sensor.is_reliable:
                sensor_area = sensor.config.get("area", "unknown")
                # Handle list of areas for display
                area_str = str(sensor_area) if isinstance(sensor_area, list) else sensor_area
                
                self._create_warning(
                    "stuck_sensor",
                    f"Sensor {sensor_id} in area {area_str} may be stuck",
                    area=area_str,
                    sensor_id=sensor_id,
                    timestamp=triggered_sensor.last_update_time,
                )
                sensor.is_reliable = False

    def handle_unexpected_motion(
        self,
        area: AreaState,
        areas: Dict[str, AreaState],
        sensors: Dict[str, SensorState],
        timestamp: float,
    ) -> bool:
        """Handle unexpected motion in an area that should be unoccupied.

        Returns:
            bool: True if this is valid entry (not an anomaly), False if anomaly detected
        """
        # Check for valid paths from occupied areas
        valid_entry = False

        # Check adjacent areas for recent activity
        adjacency = self.adjacency_map.get(area.id, [])
        
        # First pass: Look for adjacent areas with RECENT motion (high confidence)
        for adjacent_area_id in adjacency:
            if adjacent_area_id in areas:
                adjacent_area = areas[adjacent_area_id]
                if adjacent_area.occupancy > 0 and adjacent_area.has_recent_motion(
                    timestamp, self.recent_motion_window
                ):
                    # Likely moved from adjacent occupied room
                    valid_entry = True
                    logger.info(f"Person moved from {adjacent_area_id} to {area.id} (recent motion)")
                    adjacent_area.record_exit(timestamp)
                    break
        
        # Second pass: If no recent motion found, look for ANY occupied adjacent area (Sleep Scenario)
        if not valid_entry:
            for adjacent_area_id in adjacency:
                if adjacent_area_id in areas:
                    adjacent_area = areas[adjacent_area_id]
                    if adjacent_area.occupancy > 0:
                        # Moved from occupied room (even if inactive/sleeping)
                        valid_entry = True
                        logger.info(f"Person moved from {adjacent_area_id} to {area.id} (sleep/inactive)")
                        adjacent_area.record_exit(timestamp)
                        break

        if not valid_entry:
            # Could be entry from outside if this is an entry point
            if area.is_exit_capable:
                logger.info(f"Person entered {area.id} from outside")
                valid_entry = True
            else:
                logger.warning(
                    f"Unexpected motion in {area.id} without clear entry path"
                )
                self._create_warning(
                    "unexpected_motion",
                    f"Unexpected motion in {area.id}",
                    area=area.id,
                    timestamp=timestamp,
                )

        return valid_entry

    def check_simultaneous_motion(
        self, trigger_area_id: str, areas: Dict[str, AreaState], timestamp: float
    ) -> None:
        """Check for simultaneous motion in multiple areas."""
        # Get list of areas with recent motion
        areas_with_recent_motion = []
        for area_id, area in areas.items():
            if area_id != trigger_area_id and area.has_recent_motion(timestamp, 10):
                areas_with_recent_motion.append(area_id)

        if areas_with_recent_motion:
            non_adjacent = [
                area_id
                for area_id in areas_with_recent_motion
                if not self._has_path_within_hops(trigger_area_id, area_id, 2)
            ]

            if non_adjacent:
                self._create_warning(
                    "simultaneous_motion",
                    f"Motion detected simultaneously in non-adjacent areas: {trigger_area_id} and {', '.join(non_adjacent)}",
                    timestamp=timestamp,
                )

    def _has_path_within_hops(self, start: str, goal: str, max_hops: int) -> bool:
        if start == goal:
            return True
        visited = set([start])
        queue = deque([(start, 0)])

        while queue:
            node, depth = queue.popleft()
            if depth >= max_hops:
                continue
            for neighbor in self.adjacency_map.get(node, []):
                if neighbor == goal:
                    return True
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))
        return False

    def check_timeouts(self, areas: Dict[str, AreaState], timestamp: float) -> None:
        """Check for timeout conditions like inactivity and extended occupancy."""

        for area_id, area in areas.items():
            # Check exit-capable areas for auto-clear (shorter timeout)
            if area.is_exit_capable and area.occupancy > 0:
                # Exit-capable areas clear after 5 minutes of inactivity
                # (people can leave the system from these areas)
                exit_timeout = 300  # 5 minutes
                inactivity_duration = area.get_inactivity_duration(timestamp)
                
                if inactivity_duration > exit_timeout:
                    logger.info(
                        f"Auto-clearing exit-capable area {area_id} after {inactivity_duration:.0f}s of inactivity"
                    )
                    area.occupancy = 0
                    self._create_warning(
                        "exit_area_auto_clear",
                        f"Exit-capable area {area_id} was auto-cleared after {inactivity_duration / 60:.1f} minutes of inactivity",
                        area=area_id,
                        timestamp=timestamp,
                    )
                    continue  # Skip regular timeout checks for this area
            
            # Check for inactivity timeout if area is occupied
            if area.occupancy > 0:
                inactivity_duration = area.get_inactivity_duration(timestamp)

                # Reset room after 24 hours of inactivity
                if inactivity_duration > self.motion_timeout:
                    logger.warning(
                        f"Resetting area {area_id} due to {inactivity_duration / 3600:.1f} hours of inactivity"
                    )
                    area.occupancy = 0
                    self._create_warning(
                        "inactivity_timeout",
                        f"Area {area_id} was reset after {inactivity_duration / 3600:.1f} hours of inactivity",
                        area=area_id,
                        timestamp=timestamp,
                    )

                # Warning for extended occupancy (12+ hours)
                elif inactivity_duration > self.extended_occupancy_threshold:
                    # Check if we already have an active warning for this
                    has_warning = any(
                        w.is_active
                        and w.type == "extended_occupancy"
                        and w.area == area_id
                        for w in self.warnings
                    )
                    if not has_warning:
                        self._create_warning(
                            "extended_occupancy",
                            f"Area {area_id} has been occupied for {inactivity_duration / 3600:.1f} hours with limited activity",
                            area=area_id,
                            timestamp=timestamp,
                        )

    def _create_warning(
        self,
        warning_type: str,
        message: str,
        area: Optional[str] = None,
        sensor_id: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> Warning:
        """Add a warning to the system and return it."""
        if timestamp is None:
            import time

            timestamp = time.time()
        warning = Warning(warning_type, message, area, sensor_id, timestamp)
        logger.warning(f"New warning: {warning}")
        self.warnings.append(warning)
        return warning

    def get_warnings(self, active_only: bool = True) -> List[Warning]:
        """Get list of warnings, optionally filtered to active ones only."""
        if active_only:
            return [w for w in self.warnings if w.is_active]
        return self.warnings

    def resolve_warning(self, warning_id: str) -> bool:
        """Resolve a specific warning by ID."""
        for warning in self.warnings:
            if warning.id == warning_id and warning.is_active:
                warning.resolve()
                return True
        return False

    def clear_warnings(self) -> bool:
        """Resolve all active warnings."""
        cleared = False
        for warning in self.warnings:
            if warning.is_active:
                warning.resolve()
                cleared = True
        return cleared

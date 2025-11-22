from typing import Dict, Any, Optional
import time
import logging

from .helpers.sensor_state import SensorState
from .helpers.sensor_adjacency_tracker import SensorAdjacencyTracker
from .helpers.anomaly_detector import AnomalyDetector
from .area_manager import AreaManager

_LOGGER = logging.getLogger(__name__)

class SensorManager:
    """Manages sensors and processes events."""

    def __init__(
        self, 
        config: Dict[str, Any], 
        area_manager: AreaManager,
        adjacency_tracker: SensorAdjacencyTracker,
        anomaly_detector: AnomalyDetector
    ):
        self.config = config
        self.area_manager = area_manager
        self.adjacency_tracker = adjacency_tracker
        self.anomaly_detector = anomaly_detector
        self.sensors: Dict[str, SensorState] = {}
        self._initialize_sensors()
        self._initialize_adjacency()

    def _initialize_sensors(self) -> None:
        """Initialize sensor tracking objects from configuration."""
        for sensor_id, sensor_config in self.config.get("sensors", {}).items():
            self.sensors[sensor_id] = SensorState(sensor_id, sensor_config, time.time())

    def _initialize_adjacency(self) -> None:
        """Initialize sensor adjacency relationships from configuration."""
        adjacency_config = self.config.get("adjacency", {})

        # Build adjacency map for sensors based on their areas
        for sensor_id, sensor in self.sensors.items():
            area_config = sensor.config.get("area")
            if not area_config:
                continue

            # Handle both single area (str) and multiple areas (list)
            area_ids = area_config if isinstance(area_config, list) else [area_config]

            # Register sensor-to-area mapping
            for area_id in area_ids:
                self.adjacency_tracker.add_sensor_area(sensor_id, area_id)

            # Find sensors in adjacent areas
            adjacent_sensors = set()

            for area_id in area_ids:
                adjacent_areas = adjacency_config.get(area_id, [])
                
                for adjacent_area_id in adjacent_areas:
                    for other_sensor_id, other_sensor in self.sensors.items():
                        other_area_config = other_sensor.config.get("area")
                        if not other_area_config:
                            continue
                            
                        other_area_ids = other_area_config if isinstance(other_area_config, list) else [other_area_config]
                        
                        if adjacent_area_id in other_area_ids:
                            adjacent_sensors.add(other_sensor_id)

            # Set adjacency for this sensor
            self.adjacency_tracker.set_adjacency(sensor_id, adjacent_sensors)

    def process_sensor_event(
        self, sensor_id: str, state: bool, timestamp: float
    ) -> bool:
        """Process a sensor state change event. Returns True if state changed."""
        if sensor_id not in self.sensors:
            _LOGGER.warning(f"Unknown sensor ID: {sensor_id}")
            return False

        sensor = self.sensors[sensor_id]
        sensor_type = sensor.config.get("type", "")

        # Add debug logging for motion sensors
        if sensor_type in ["motion", "camera_motion", "camera_person"]:
            _LOGGER.debug(
                f"Motion sensor event: {sensor_id}, state={state}, type={sensor_type}"
            )

        state_changed = sensor.update_state(state, timestamp)

        # Add more debug logging about the state change result
        if sensor_type in ["motion", "camera_motion", "camera_person"]:
            _LOGGER.debug(f"Motion sensor {sensor_id} state_changed={state_changed}")

        # Skip processing if state didn't actually change
        if not state_changed and state is True:
            # Only motion sensors have meaningful repeated "ON" states
            if sensor.config.get("type", "") in [
                "motion",
                "camera_motion",
                "camera_person",
            ]:
                _LOGGER.debug(f"Processing repeated motion for {sensor_id}")
                self._process_repeated_motion(sensor_id, timestamp)
            return False

        # Process different sensor types
        if sensor_type in ["motion", "camera_motion", "camera_person"] and state:
            _LOGGER.debug(f"Processing motion event for {sensor_id}")
            self._process_motion_event(sensor_id, timestamp)

        elif sensor_type == "magnetic":
            self._process_magnetic_event(sensor_id, state, timestamp)

        # Check for stuck sensors after processing the event
        self._check_for_stuck_sensors(sensor_id, timestamp)
        
        return True

    def _check_for_stuck_sensors(
        self, triggered_sensor_id: str, timestamp: float
    ) -> None:
        """Check for stuck sensors when a sensor is triggered."""
        triggered_sensor = self.sensors[triggered_sensor_id]
        area_config = triggered_sensor.config.get("area")

        if not area_config:
            return
            
        area_ids = area_config if isinstance(area_config, list) else [area_config]
        
        # Record motion in adjacency tracker for all areas
        for area_id in area_ids:
            if self.area_manager.get_area(area_id):
                self.adjacency_tracker.record_motion(area_id, timestamp)

        # Delegate to anomaly detector for checking stuck sensors
        self.anomaly_detector.check_for_stuck_sensors(
            self.sensors, self.area_manager.get_all_areas(), triggered_sensor_id
        )

    def _process_repeated_motion(self, sensor_id: str, timestamp: float) -> None:
        """Handle repeated motion events from the same sensor."""
        sensor = self.sensors[sensor_id]
        area_config = sensor.config.get("area")

        if not area_config:
            return
            
        area_ids = area_config if isinstance(area_config, list) else [area_config]

        for area_id in area_ids:
            if not self.area_manager.get_area(area_id):
                continue

            # Record motion in the area
            self.area_manager.record_motion(area_id, timestamp)

            # Update motion in adjacency tracker
            self.adjacency_tracker.record_motion(area_id, timestamp)

    def _process_motion_event(self, sensor_id: str, timestamp: float) -> None:
        """Process motion sensor activation."""
        sensor = self.sensors[sensor_id]
        area_config = sensor.config.get("area")

        if not area_config:
            _LOGGER.warning(f"Sensor {sensor_id} is not associated with a valid area")
            return
            
        area_ids = area_config if isinstance(area_config, list) else [area_config]
        
        for area_id in area_ids:
            area = self.area_manager.get_area(area_id)
            if not area:
                _LOGGER.warning(f"Sensor {sensor_id} associated with unknown area {area_id}")
                continue

            # Record motion in the area
            area.record_motion(timestamp)

            # Record motion in adjacency tracker
            self.adjacency_tracker.record_motion(area_id, timestamp)

            # Check for unexpected motion
            if area.occupancy == 0:
                # Get current probability to inform decision
                current_prob = self.area_manager.get_occupancy_probability(area_id)
                self._handle_unexpected_motion(area, timestamp, current_prob)

            # Check for simultaneous motion in adjacent areas
            self._check_simultaneous_motion(area_id, timestamp)

    def _process_magnetic_event(
        self, sensor_id: str, state: bool, timestamp: float
    ) -> None:
        """Process door/window sensor events."""
        sensor = self.sensors[sensor_id]
        between_areas = sensor.config.get("between_areas", [])

        if len(between_areas) != 2:
            _LOGGER.warning(
                f"Magnetic sensor {sensor_id} has invalid between_areas configuration"
            )
            return

        # Door/window events are generally just recorded but don't directly change occupancy
        # They help confirm transitions between areas
        
        # When door opens, record activity in both connected areas to facilitate transitions
        if state:
            _LOGGER.debug(f"Magnetic sensor {sensor_id} opened between {between_areas}")
            for area_id in between_areas:
                # Update adjacency tracker so subsequent motion in either area 
                # is considered a valid transition
                self.adjacency_tracker.record_motion(area_id, timestamp)
                
                # Also update area last_motion to keep the area "active" in terms of 
                # probability decay if it's already occupied
                area = self.area_manager.get_area(area_id)
                if area and area.occupancy > 0:
                    area.record_motion(timestamp)

    def _handle_unexpected_motion(self, area: Any, timestamp: float, probability: float = 0.0) -> None:
        """Handle unexpected motion in an area that should be unoccupied."""
        # Delegate to anomaly detector to evaluate if this is a valid entry or anomaly
        self.anomaly_detector.handle_unexpected_motion(
            area, self.area_manager.get_all_areas(), self.sensors, timestamp, self.adjacency_tracker
        )

        # Always increment occupancy - if valid_entry is True, the person moved from
        # an adjacent area (which was decremented). If False, it's a new entry or anomaly.
        # Either way, someone is now in this area.
        area.record_entry(timestamp)

    def _check_simultaneous_motion(
        self, trigger_area_id: str, timestamp: float
    ) -> None:
        """Check for simultaneous motion in multiple areas."""
        # Delegate to anomaly detector to check for simultaneous motion anomalies
        self.anomaly_detector.check_simultaneous_motion(
            trigger_area_id, self.area_manager.get_all_areas(), timestamp
        )

    def reset(self) -> None:
        """Reset all sensors."""
        for sensor in self.sensors.values():
            sensor.current_state = False
            sensor.history = []
            sensor.is_reliable = True

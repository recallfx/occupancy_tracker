from typing import Dict, Any, Optional
import time
import logging

from .helpers.sensor_state import SensorState
from .helpers.anomaly_detector import AnomalyDetector
from .helpers.map_state_recorder import MapStateRecorder
from .area_manager import AreaManager
from .helpers.area_state import AreaState

_LOGGER = logging.getLogger(__name__)

class SensorManager:
    """Manages sensors and processes events."""

    def __init__(
        self, 
        config: Dict[str, Any], 
        area_manager: AreaManager,
        anomaly_detector: AnomalyDetector,
        state_recorder: Optional[MapStateRecorder] = None,
    ):
        self.config = config
        self.area_manager = area_manager
        self.anomaly_detector = anomaly_detector
        self.state_recorder = state_recorder
        self.sensors: Dict[str, SensorState] = {}

        self._initialize_sensors()

    def _initialize_sensors(self) -> None:
        """Initialize sensor tracking objects from configuration."""
        for sensor_id, sensor_config in self.config.get("sensors", {}).items():
            self.sensors[sensor_id] = SensorState(sensor_id, sensor_config, time.time())


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
        if not state_changed:
            return False

        # Process different sensor types
        if sensor_type in ["motion", "camera_motion", "camera_person"] and state:
            _LOGGER.debug(f"Processing motion event for {sensor_id}")
            self._process_motion_event(sensor_id, timestamp)

        elif sensor_type == "magnetic":
            self._process_magnetic_event(sensor_id, state, timestamp)

        # Check for stuck sensors after processing the event
        self._check_for_stuck_sensors(sensor_id, timestamp)

        self._record_snapshot(sensor_id, state, timestamp)
        
        return True

    def _check_for_stuck_sensors(
        self, triggered_sensor_id: str, timestamp: float
    ) -> None:
        """Check for stuck sensors when a sensor is triggered."""
        # Delegate to anomaly detector for checking stuck sensors
        self.anomaly_detector.check_for_stuck_sensors(
            self.sensors, self.area_manager.get_all_areas(), triggered_sensor_id
        )

    def _record_snapshot(self, sensor_id: str, state: bool, timestamp: float) -> None:
        """Capture a map snapshot after applying a new sensor state."""
        if not self.state_recorder:
            return
        self.state_recorder.record_sensor_event(
            timestamp=timestamp,
            sensor_id=sensor_id,
            new_state=state,
            areas=self.area_manager.get_all_areas(),
            sensors=self.sensors,
        )

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
            was_occupied = area.is_occupied
            area.record_motion(timestamp)

            # If the area was previously empty, treat this as a potential entry
            if not was_occupied:
                self._handle_unexpected_motion(area, timestamp)

            # Check for simultaneous motion in adjacent areas
            self._check_simultaneous_motion(area_id, timestamp)

    def _process_magnetic_event(
        self, sensor_id: str, state: bool, timestamp: float
    ) -> None:
        """Process door/window sensor events."""
        sensor = self.sensors[sensor_id]
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
                f"Magnetic sensor {sensor_id} has invalid between_areas configuration"
            )
            return

        # Door/window events are generally just recorded but don't directly change occupancy
        # They help confirm transitions between areas
        
        # When door opens, record activity in both connected areas to facilitate transitions
        if state:
            _LOGGER.debug(f"Magnetic sensor {sensor_id} opened between {between_areas}")
            for area_id in between_areas:
                # Refresh each area's motion timestamp so decay logic stays accurate
                area = self.area_manager.get_area(area_id)
                if area:
                    area.record_motion(timestamp)

    def _handle_unexpected_motion(self, area: Any, timestamp: float) -> None:
        """Handle unexpected motion in an area that should be unoccupied."""
        # Delegate to anomaly detector to evaluate if this is a valid entry or anomaly
        self.anomaly_detector.handle_unexpected_motion(
            area, self.area_manager.get_all_areas(), self.sensors, timestamp
        )

        # Always increment occupancy - if valid_entry is True, the person moved from
        # an adjacent area (which was decremented). If False, it's a new entry or anomaly.
        # Either way, someone is now in this area.
        # Note: This design choice prioritizes tracking robustness over false positive rejection.
        # A false positive will create "ghost" occupancy, but ignoring anomalies would cause
        # the system to lose track of people who enter via unmonitored paths.
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

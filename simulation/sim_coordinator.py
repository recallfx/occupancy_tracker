import asyncio
import logging
import time
import sys
import os

# Add repository root to python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from custom_components.occupancy_tracker.coordinator import OccupancyCoordinator
from custom_components.occupancy_tracker.helpers.anomaly_detector import AnomalyDetector
from custom_components.occupancy_tracker.helpers.map_state_recorder import MapStateRecorder
from custom_components.occupancy_tracker.helpers.map_occupancy_resolver import MapOccupancyResolver
from custom_components.occupancy_tracker.helpers.area_state import AreaState
from custom_components.occupancy_tracker.helpers.sensor_state import SensorState
from custom_components.occupancy_tracker.diagnostics import OccupancyDiagnostics

_LOGGER = logging.getLogger(__name__)

class SimOccupancyCoordinator(OccupancyCoordinator):
    def __init__(self, config):
        # Skip super().__init__ to avoid HA dependency issues
        self.hass = None
        self.logger = logging.getLogger(__name__)
        self.name = "occupancy_tracker"
        self._listeners = []
        
        self.config = config
        self.last_event_time = time.time()
        
        # Initialize state dictionaries directly
        self.areas = {}
        self.sensors = {}
        self._initialize_areas(config)
        self._initialize_sensors(config)
        
        # Initialize helpers
        self.anomaly_detector = AnomalyDetector(config)
        self.state_recorder = MapStateRecorder()
        self.occupancy_resolver = MapOccupancyResolver(config)
        self.diagnostics = OccupancyDiagnostics(self)
        self.data = self.get_simulation_state()
    
    def _initialize_areas(self, config):
        """Initialize area tracking objects from configuration."""
        for area_id, area_config in config.get("areas", {}).items():
            self.areas[area_id] = AreaState(area_id, area_config)
    
    def _initialize_sensors(self, config):
        """Initialize sensor tracking objects from configuration."""
        for sensor_id, sensor_config in config.get("sensors", {}).items():
            self.sensors[sensor_id] = SensorState(sensor_id, sensor_config, time.time())

    def get_simulation_state(self, timestamp=None):
        """Get comprehensive state for simulation."""
        now = timestamp if timestamp is not None else time.time()
        
        history_count = len(self.state_recorder.get_history())
        
        # Get area states
        areas = {}
        for area_id, area in self.areas.items():
            areas[area_id] = {
                "occupancy": area.occupancy,
                "probability": self.get_occupancy_probability(area_id, now),
                "last_motion": area.last_motion,
                "time_since_motion": now - area.last_motion if area.last_motion > 0 else None,
                "is_indoors": area.is_indoors,
                "is_exit_capable": area.is_exit_capable
            }
            
        # Get sensor states
        sensors = {}
        for sensor_id, sensor in self.sensors.items():
            sensors[sensor_id] = {
                "state": sensor.current_state,
                "last_changed": sensor.last_changed,
                "time_since_change": now - sensor.last_changed if sensor.last_changed > 0 else None,
                "type": sensor.config.get("type"),
                "is_stuck": sensor.is_stuck
            }
            
        # Get warnings
        warnings = [
            {
                "id": w.id,
                "type": w.type,
                "message": w.message,
                "area_id": w.area,
                "sensor_id": w.sensor_id,
                "timestamp": w.timestamp
            }
            for w in self.get_warnings(active_only=True)
        ]
        
        result = {
            "areas": areas,
            "sensors": sensors,
            "warnings": warnings,
            "last_event_time": self.last_event_time,
            "timestamp": now,
            "history_count": history_count
        }
        return result

    def process_sensor_event(self, sensor_id: str, state: bool, timestamp: float) -> None:
        """Process a sensor state change event."""
        # Validate sensor exists
        if sensor_id not in self.sensors:
            _LOGGER.warning(f"Unknown sensor ID: {sensor_id}")
            return
        
        sensor = self.sensors[sensor_id]
        sensor_type = sensor.config.get("type", "")
        area_ids = sensor.config.get("area", [])
        if isinstance(area_ids, str):
            area_ids = [area_ids]
        
        # Capture state before processing
        old_occupancy = {aid: self.areas[aid].occupancy for aid in area_ids if aid in self.areas}
        
        # Update sensor state
        state_changed = sensor.update_state(state, timestamp)
        
        # Skip processing if state didn't actually change
        if not state_changed:
            return
        
        # Record snapshot
        snapshot = self._record_snapshot(sensor_id, state, timestamp)
        
        # Process snapshot through the resolver
        if snapshot:
            self.occupancy_resolver.process_snapshot(
                snapshot,
                self.areas,
                self.sensors,
                self.anomaly_detector,
            )
            self._refresh_latest_snapshot_state()
            
            # Log detailed state changes
            self._log_state_change(sensor_id, sensor_type, state, area_ids, old_occupancy, timestamp)
            
            # Check for stuck sensors after processing
            self._check_for_stuck_sensors(sensor_id, timestamp)
            
            self.last_event_time = timestamp
            # Use simulation state instead of diagnostics
            self.async_set_updated_data(self.get_simulation_state())

    def check_timeouts(self, timestamp: float = None) -> None:
        """Check for timeout conditions."""
        if timestamp is None:
            timestamp = time.time()
        self.anomaly_detector.check_timeouts(self.areas, timestamp)
        self.state_recorder.maybe_record_tick(
            timestamp,
            self.areas,
            self.sensors,
        )
        self.async_set_updated_data(self.get_simulation_state())

    def reset_warnings(self) -> None:
        """Clear warnings and refresh the simulation payload."""
        if self.anomaly_detector.clear_warnings():
            self.async_set_updated_data(self.get_simulation_state())

    def resolve_warning(self, warning_id: str) -> None:
        """Resolve a single warning and refresh state if changed."""
        if self.anomaly_detector.resolve_warning(warning_id):
            self.async_set_updated_data(self.get_simulation_state())

    def async_add_listener(self, callback):
        self._listeners.append(callback)
    
    def async_remove_listener(self, callback):
        if callback in self._listeners:
            self._listeners.remove(callback)
        
    def async_set_updated_data(self, data):
        self.data = data
        _LOGGER.debug(f"async_set_updated_data called with history_count={data.get('history_count', 'missing')}")
        for callback in self._listeners:
            if asyncio.iscoroutinefunction(callback):
                asyncio.create_task(callback())
            else:
                callback()

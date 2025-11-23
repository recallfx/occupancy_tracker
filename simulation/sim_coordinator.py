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
from custom_components.occupancy_tracker.area_manager import AreaManager
from custom_components.occupancy_tracker.sensor_manager import SensorManager
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
        
        # Initialize helpers
        self.anomaly_detector = AnomalyDetector(config)
        self.state_recorder = MapStateRecorder()
        self.area_manager = AreaManager(config)
        self.sensor_manager = SensorManager(
            config, 
            self.area_manager, 
            self.anomaly_detector,
            state_recorder=self.state_recorder,
        )
        self.diagnostics = OccupancyDiagnostics(self)
        self.data = self.get_simulation_state()

    def get_simulation_state(self):
        """Get comprehensive state for simulation."""
        now = time.time()
        
        # Get area states
        areas = {}
        for area_id, area in self.area_manager.get_all_areas().items():
            areas[area_id] = {
                "occupancy": area.occupancy,
                "probability": self.area_manager.get_occupancy_probability(area_id, now),
                "last_motion": area.last_motion,
                "time_since_motion": now - area.last_motion if area.last_motion > 0 else None,
                "is_indoors": area.is_indoors,
                "is_exit_capable": area.is_exit_capable
            }
            
        # Get sensor states
        sensors = {}
        for sensor_id, sensor in self.sensor_manager.sensors.items():
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
        
        return {
            "areas": areas,
            "sensors": sensors,
            "warnings": warnings,
            "last_event_time": self.last_event_time,
            "timestamp": now
        }

    def process_sensor_event(self, sensor_id: str, state: bool, timestamp: float) -> None:
        """Process a sensor state change event."""
        if self.sensor_manager.process_sensor_event(sensor_id, state, timestamp):
            self.last_event_time = timestamp
            self.async_set_updated_data(self.get_simulation_state())

    def check_timeouts(self, timestamp: float = None) -> None:
        """Check for timeout conditions."""
        if timestamp is None:
            timestamp = time.time()
        self.anomaly_detector.check_timeouts(self.area_manager.get_all_areas(), timestamp)
        self.state_recorder.maybe_record_tick(
            timestamp,
            self.area_manager.get_all_areas(),
            self.sensor_manager.sensors,
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
        for callback in self._listeners:
            if asyncio.iscoroutinefunction(callback):
                asyncio.create_task(callback())
            else:
                callback()

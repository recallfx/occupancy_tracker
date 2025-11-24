from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .helpers.types import OccupancyTrackerConfig
from .helpers.anomaly_detector import AnomalyDetector
from .helpers.warning import Warning
from .helpers.map_state_recorder import MapStateRecorder, MapSnapshot
from .helpers.map_occupancy_resolver import MapOccupancyResolver
from .helpers.area_state import AreaState
from .helpers.sensor_state import SensorState
from .diagnostics import OccupancyDiagnostics

_LOGGER = logging.getLogger(__name__)

class OccupancyCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Coordinator for Occupancy Tracker."""

    def __init__(self, hass: HomeAssistant, config: OccupancyTrackerConfig) -> None:
        """Initialize the coordinator."""
        request_refresh_debouncer = Debouncer(
            hass,
            _LOGGER,
            cooldown=0,
            immediate=True,
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,
            request_refresh_debouncer=request_refresh_debouncer,
        )
        self.config = config
        self.last_event_time = time.time()
        
        # Initialize state dictionaries directly
        self.areas: Dict[str, AreaState] = {}
        self.sensors: Dict[str, SensorState] = {}
        self._initialize_areas(config)
        self._initialize_sensors(config)
        
        # Initialize helpers
        self.anomaly_detector = AnomalyDetector(config)
        self.state_recorder = MapStateRecorder()
        self.occupancy_resolver = MapOccupancyResolver(config)
        
        # Initialize diagnostics
        self.diagnostics = OccupancyDiagnostics(self)
    
    def _initialize_areas(self, config: OccupancyTrackerConfig) -> None:
        """Initialize area tracking objects from configuration."""
        for area_id, area_config in config.get("areas", {}).items():
            self.areas[area_id] = AreaState(area_id, area_config)
    
    def _initialize_sensors(self, config: OccupancyTrackerConfig) -> None:
        """Initialize sensor tracking objects from configuration."""
        for sensor_id, sensor_config in config.get("sensors", {}).items():
            self.sensors[sensor_id] = SensorState(sensor_id, sensor_config, time.time())

    def process_sensor_event(
        self, sensor_id: str, state: bool, timestamp: float
    ) -> None:
        """Process a sensor state change event."""
        # Validate sensor exists
        if sensor_id not in self.sensors:
            _LOGGER.warning(f"Unknown sensor ID: {sensor_id}")
            return
        
        sensor = self.sensors[sensor_id]
        sensor_type = sensor.config.get("type", "")
        
        # Add debug logging for motion sensors
        if sensor_type in ["motion", "camera_motion", "camera_person"]:
            _LOGGER.debug(
                f"Motion sensor event: {sensor_id}, state={state}, type={sensor_type}"
            )
        
        # Update sensor state
        state_changed = sensor.update_state(state, timestamp)
        
        # Add more debug logging about the state change result
        if sensor_type in ["motion", "camera_motion", "camera_person"]:
            _LOGGER.debug(f"Motion sensor {sensor_id} state_changed={state_changed}")
        
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
            
            # Check for stuck sensors after processing
            self._check_for_stuck_sensors(sensor_id, timestamp)
            
            self.last_event_time = timestamp
            self.async_set_updated_data(self.diagnostics.get_system_status())
    
    def _record_snapshot(
        self, sensor_id: str, state: bool, timestamp: float
    ) -> Optional[MapSnapshot]:
        """Capture a map snapshot that will be used to derive occupancy."""
        return self.state_recorder.record_sensor_event(
            timestamp=timestamp,
            sensor_id=sensor_id,
            new_state=state,
            areas=self.areas,
            sensors=self.sensors,
        )
    
    def _refresh_latest_snapshot_state(self) -> None:
        """Update the latest snapshot with current state."""
        self.state_recorder.update_latest_state(
            self.areas,
            self.sensors,
        )
    
    def _check_for_stuck_sensors(
        self, triggered_sensor_id: str, timestamp: float
    ) -> None:
        """Check for stuck sensors when a sensor is triggered."""
        self.anomaly_detector.check_for_stuck_sensors(
            self.sensors,
            self.areas,
            triggered_sensor_id
        )

    def get_occupancy(self, area_id: str) -> int:
        """Get current occupancy count for an area."""
        area = self.areas.get(area_id)
        return area.occupancy if area else 0

    def get_occupancy_probability(self, area_id: str, timestamp: float = None) -> float:
        """Get probability score (0-1) that area is occupied."""
        area = self.areas.get(area_id)
        if not area:
            return 0.0

        now = timestamp if timestamp is not None else time.time()

        if area.occupancy <= 0:
            return 0.0

        # If area is occupied but no motion ever recorded (e.g. manually set),
        # assume high confidence
        if area.last_motion == 0:
            return 1.0

        time_since_motion = now - area.last_motion
        
        # High confidence period (0-60s)
        if time_since_motion < 60:
            return 1.0
            
        # Medium confidence period (1-5 mins)
        if time_since_motion < 300:
            return 0.9
            
        # Decay period (> 5 mins)
        # Decay from 0.9 down to 0.1 over 1 hour (3600s)
        k = 0.00021
        decay_time = time_since_motion - 300
        probability = 0.1 + 0.8 * math.exp(-k * decay_time)
        
        return round(probability, 2)

    def get_warnings(self, active_only: bool = True) -> List[Warning]:
        """Get list of warnings."""
        return self.anomaly_detector.get_warnings(active_only)

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
        # Always update data to reflect probability decay
        self.async_set_updated_data(self.diagnostics.get_system_status())

    def resolve_warning(self, warning_id: str) -> bool:
        """Resolve a specific warning by ID."""
        result = self.anomaly_detector.resolve_warning(warning_id)
        if result:
            self.async_set_updated_data(self.diagnostics.get_system_status())
        return result

    def get_area_status(self, area_id: str) -> Dict[str, Any]:
        """Get detailed status information for an area."""
        return self.diagnostics.get_area_status(area_id)

    def get_system_status(self) -> Dict[str, Any]:
        """Get overall system status information."""
        return self.diagnostics.get_system_status()

    def reset_anomalies(self) -> None:
        """Reset the anomaly detection system without resetting occupancy state."""
        self.anomaly_detector = AnomalyDetector(self.config)
        _LOGGER.info("Anomaly detection system reset")
        self.async_set_updated_data(self.diagnostics.get_system_status())

    def reset_warnings(self) -> None:
        """Clear all active warnings without altering other state."""
        if self.anomaly_detector.clear_warnings():
            _LOGGER.info("Active warnings cleared")
            self.async_set_updated_data(self.diagnostics.get_system_status())

    def reset(self) -> None:
        """Reset the entire system state."""
        # Reset all areas
        for area in self.areas.values():
            area.occupancy = 0
            area.last_motion = 0
            area.activity_history = []
        
        # Reset all sensors
        for sensor in self.sensors.values():
            sensor.current_state = False
            sensor.history = []
            sensor.is_reliable = True
        
        self.occupancy_resolver.reset()
        
        # Create new anomaly detector and state recorder
        self.anomaly_detector = AnomalyDetector(self.config)
        self.state_recorder.reset()

        _LOGGER.info("Occupancy tracker system reset")
        self.async_set_updated_data(self.diagnostics.get_system_status())
    
    def rebuild_from_history(self) -> None:
        """Rebuild occupancy state from recorded history."""
        history = self.state_recorder.get_history()
        if not history:
            return
        
        self.occupancy_resolver.recalculate_from_history(
            history,
            self.areas,
            self.sensors,
            self.anomaly_detector,
        )
        self._refresh_latest_snapshot_state()

    def diagnose_motion_issues(self, sensor_id: str = None) -> Dict[str, Any]:
        """Diagnostic method to help identify why motion isn't being detected."""
        return self.diagnostics.diagnose_motion_issues(sensor_id)

    async def _async_update_data(self) -> Dict[str, Any]:
        """Provide coordinator state when HA requests a refresh."""
        return self.diagnostics.get_system_status()

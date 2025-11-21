from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .helpers.types import OccupancyTrackerConfig
from .helpers.sensor_adjacency_tracker import SensorAdjacencyTracker
from .helpers.anomaly_detector import AnomalyDetector
from .helpers.warning import Warning
from .area_manager import AreaManager
from .sensor_manager import SensorManager

_LOGGER = logging.getLogger(__name__)

class OccupancyCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Coordinator for Occupancy Tracker."""

    def __init__(self, hass: HomeAssistant, config: OccupancyTrackerConfig) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,
        )
        self.config = config
        self.last_event_time = time.time()
        
        # Initialize helpers
        self.adjacency_tracker = SensorAdjacencyTracker()
        self.anomaly_detector = AnomalyDetector(config)
        
        # Initialize managers
        self.area_manager = AreaManager(config)
        self.sensor_manager = SensorManager(
            config, 
            self.area_manager, 
            self.adjacency_tracker, 
            self.anomaly_detector
        )

    def process_sensor_event(
        self, sensor_id: str, state: bool, timestamp: float
    ) -> None:
        """Process a sensor state change event."""
        if self.sensor_manager.process_sensor_event(sensor_id, state, timestamp):
            self.last_event_time = timestamp
            self.async_set_updated_data(self.get_system_status())

    def get_occupancy(self, area_id: str) -> int:
        """Get current occupancy count for an area."""
        return self.area_manager.get_occupancy(area_id)

    def get_occupancy_probability(self, area_id: str) -> float:
        """Get probability score (0-1) that area is occupied."""
        return self.area_manager.get_occupancy_probability(area_id)

    def get_warnings(self, active_only: bool = True) -> List[Warning]:
        """Get list of warnings."""
        return self.anomaly_detector.get_warnings(active_only)

    def check_timeouts(self, timestamp: float = None) -> None:
        """Check for timeout conditions."""
        if timestamp is None:
            timestamp = time.time()
        self.anomaly_detector.check_timeouts(self.area_manager.get_all_areas(), timestamp)
        # Always update data to reflect probability decay
        self.async_set_updated_data(self.get_system_status())

    def resolve_warning(self, warning_id: str) -> bool:
        """Resolve a specific warning by ID."""
        result = self.anomaly_detector.resolve_warning(warning_id)
        if result:
            self.async_set_updated_data(self.get_system_status())
        return result

    def get_area_status(self, area_id: str) -> Dict[str, Any]:
        """Get detailed status information for an area."""
        area = self.area_manager.get_area(area_id)
        if not area:
            return {"error": "Area not found"}

        now = time.time()
        return {
            "id": area_id,
            "name": area.config.get("name", area_id),
            "occupancy": area.occupancy,
            "last_motion": area.last_motion,
            "time_since_motion": now - area.last_motion
            if area.last_motion > 0
            else None,
            "indoors": area.is_indoors,
            "exit_capable": area.is_exit_capable,
            "adjacent_areas": self.config.get("adjacency", {}).get(area_id, []),
        }

    def get_system_status(self) -> Dict[str, Any]:
        """Get overall system status information."""
        areas = self.area_manager.get_all_areas()
        occupied_areas = [
            (area_id, area.occupancy)
            for area_id, area in areas.items()
            if area.occupancy > 0
        ]

        return {
            "total_occupancy": sum(occ for _, occ in occupied_areas),
            "occupied_areas": dict(occupied_areas),
            "active_warnings": len(self.get_warnings(active_only=True)),
            "last_event_time": self.last_event_time,
            "uptime": time.time() - self.last_event_time,
        }

    def reset_anomalies(self) -> None:
        """Reset the anomaly detection system without resetting occupancy state."""
        self.anomaly_detector = AnomalyDetector(self.config)
        # Re-link anomaly detector to sensor manager
        self.sensor_manager.anomaly_detector = self.anomaly_detector
        _LOGGER.info("Anomaly detection system reset")
        self.async_set_updated_data(self.get_system_status())

    def reset(self) -> None:
        """Reset the entire system state."""
        self.area_manager.reset()
        self.sensor_manager.reset()
        
        # Reset adjacency tracker
        self.adjacency_tracker = SensorAdjacencyTracker()
        self.sensor_manager.adjacency_tracker = self.adjacency_tracker
        self.sensor_manager._initialize_adjacency()

        # Create new anomaly detector
        self.anomaly_detector = AnomalyDetector(self.config)
        self.sensor_manager.anomaly_detector = self.anomaly_detector

        _LOGGER.info("Occupancy tracker system reset")
        self.async_set_updated_data(self.get_system_status())

    def diagnose_motion_issues(self, sensor_id: str = None) -> Dict[str, Any]:
        """Diagnostic method to help identify why motion isn't being detected."""
        sensors_to_check = [sensor_id] if sensor_id else list(self.sensor_manager.sensors.keys())
        results = {}

        for s_id in sensors_to_check:
            if s_id not in self.sensor_manager.sensors:
                results[s_id] = {"error": "Sensor not found"}
                continue

            sensor = self.sensor_manager.sensors[s_id]
            sensor_type = sensor.config.get("type", "unknown")
            area_id = sensor.config.get("area")

            sensor_info = {
                "sensor_type": sensor_type,
                "is_motion_sensor": sensor_type
                in ["motion", "camera_motion", "camera_person"],
                "current_state": sensor.current_state,
                "area_id": area_id,
                "area_exists": area_id in self.area_manager.areas if area_id else False,
                "history_length": len(sensor.history)
                if hasattr(sensor, "history")
                else "unknown",
                "is_reliable": sensor.is_reliable
                if hasattr(sensor, "is_reliable")
                else "unknown",
            }

            # Add area information if applicable
            if area_id and area_id in self.area_manager.areas:
                area = self.area_manager.areas[area_id]
                sensor_info["area_info"] = {
                    "occupancy": area.occupancy,
                    "last_motion": area.last_motion,
                    "time_since_motion": time.time() - area.last_motion
                    if area.last_motion > 0
                    else None,
                    "activity_history_length": len(area.activity_history),
                }

            results[s_id] = sensor_info

        return results

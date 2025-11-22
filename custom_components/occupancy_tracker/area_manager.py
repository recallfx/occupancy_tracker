from typing import Dict, Any, Optional
import time
import logging

from .helpers.area_state import AreaState

_LOGGER = logging.getLogger(__name__)

class AreaManager:
    """Manages area states and logic."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.areas: Dict[str, AreaState] = {}
        self._initialize_areas()

    def _initialize_areas(self) -> None:
        """Initialize area tracking objects from configuration."""
        for area_id, area_config in self.config.get("areas", {}).items():
            self.areas[area_id] = AreaState(area_id, area_config)

    def get_area(self, area_id: str) -> Optional[AreaState]:
        """Get an area by ID."""
        return self.areas.get(area_id)

    def get_all_areas(self) -> Dict[str, AreaState]:
        """Get all areas."""
        return self.areas

    def record_motion(self, area_id: str, timestamp: float) -> None:
        """Record motion in an area."""
        if area_id in self.areas:
            self.areas[area_id].record_motion(timestamp)

    def record_entry(self, area_id: str, timestamp: float) -> None:
        """Record entry into an area."""
        if area_id in self.areas:
            self.areas[area_id].record_entry(timestamp)

    def get_occupancy(self, area_id: str) -> int:
        """Get current occupancy count for an area."""
        if area_id not in self.areas:
            return 0
        return self.areas[area_id].occupancy

    def get_occupancy_probability(self, area_id: str, timestamp: float = None) -> float:
        """Get probability score (0-1) that area is occupied."""
        if area_id not in self.areas:
            return 0.0

        area = self.areas[area_id]
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
        # Formula: P(t) = 0.1 + 0.8 * e^(-k * (t - 300))
        # We want P(3600) approx 0.5
        # 0.5 = 0.1 + 0.8 * e^(-k * 3300)
        # 0.4 = 0.8 * e^(-k * 3300)
        # 0.5 = e^(-k * 3300)
        # ln(0.5) = -k * 3300
        # -0.693 = -k * 3300
        # k approx 0.00021
        
        k = 0.00021
        decay_time = time_since_motion - 300
        import math
        probability = 0.1 + 0.8 * math.exp(-k * decay_time)
        
        return round(probability, 2)

    def reset(self) -> None:
        """Reset all areas."""
        for area in self.areas.values():
            area.occupancy = 0
            area.last_motion = 0
            area.activity_history = []

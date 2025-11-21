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

    def get_occupancy_probability(self, area_id: str) -> float:
        """Get probability score (0-1) that area is occupied."""
        if area_id not in self.areas:
            return 0.05

        area = self.areas[area_id]
        now = time.time()

        if area.occupancy <= 0:
            return 0.05

        # If there's been motion in the last 5 minutes, high probability
        if now - area.last_motion < 300:
            return 0.95

        # Occupied but no recent motion - slightly lower probability
        return 0.75

    def reset(self) -> None:
        """Reset all areas."""
        for area in self.areas.values():
            area.occupancy = 0
            area.last_motion = 0
            area.activity_history = []

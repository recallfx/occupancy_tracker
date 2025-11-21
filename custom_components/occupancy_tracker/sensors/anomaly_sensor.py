"""Sensor for anomaly detection."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..coordinator import OccupancyCoordinator


class AnomalySensor(CoordinatorEntity, SensorEntity):
    """Sensor for detected anomalies.

    Reports both the count of anomalies and detailed information including:
    - Anomaly type (stuck_sensor, unexpected_motion, simultaneous_motion, etc.)
    - Affected areas and sensors
    - Timestamps and durations
    - Additional context like occupancy counts
    """

    def __init__(self, coordinator: OccupancyCoordinator):
        super().__init__(coordinator)
        self._attr_name = "Detected Anomalies"
        self._attr_unique_id = "detected_anomalies"
        self._attr_icon = "mdi:alert-circle"

    @property
    def state(self):
        """Return the count of detected anomalies."""
        return len(self.coordinator.get_warnings(active_only=True))

    @property
    def extra_state_attributes(self):
        """Return detailed state attributes about anomalies.

        Returns:
            dict: Contains:
                - List of all anomalies with full details
                - Count of each anomaly type
                - Latest anomaly details
                - Affected areas/sensors summary
        """
        warnings = self.coordinator.get_warnings(active_only=True)

        # Convert warnings to dictionary representation
        anomalies = []
        for warning in warnings:
            anomaly = {
                "id": warning.id,
                "type": warning.type,
                "message": warning.message,
                "timestamp": warning.timestamp,
                "is_active": warning.is_active,
            }

            if warning.area:
                anomaly["area"] = warning.area
            if warning.sensor_id:
                anomaly["sensor"] = warning.sensor_id

            anomalies.append(anomaly)

        # Count anomalies by type
        type_counts = {}
        affected_areas = set()
        affected_sensors = set()

        for anomaly in anomalies:
            atype = anomaly.get("type", "unknown")
            type_counts[atype] = type_counts.get(atype, 0) + 1

            if "area" in anomaly:
                affected_areas.add(anomaly["area"])
            if "sensor" in anomaly:
                affected_sensors.add(anomaly["sensor"])

        return {
            "anomalies": anomalies,  # Full list of anomaly records
            "anomaly_counts": type_counts,  # Count by type
            "latest_anomaly": anomalies[-1]
            if anomalies
            else None,  # Most recent anomaly
            "affected_areas": list(affected_areas),  # List of areas with anomalies
            "affected_sensors": list(
                affected_sensors
            ),  # List of sensors with anomalies
            "total_affected_areas": len(affected_areas),
            "total_affected_sensors": len(affected_sensors),
        }

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return True

    @property
    def device_class(self) -> str:
        """Return the device class."""
        return "problem"

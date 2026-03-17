"""Configuration for integration tests."""

from __future__ import annotations

import time

import pytest
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion

from custom_components.occupancy_tracker.coordinator import OccupancyCoordinator
from custom_components.occupancy_tracker.helpers.map_state_recorder import MapSnapshot


class SensorEventHelper:
    """Helper to trigger sensor events with precise timestamps.

    Uses real wall-clock time as the base so that timestamps are compatible
    with the coordinator's periodic ``check_timeouts`` (which calls
    ``time.time()``).  Explicit ``timestamp`` values are treated as offsets
    from the base.
    """

    def __init__(self, coordinator: OccupancyCoordinator):
        self.coordinator = coordinator
        self._base_time = time.time()
        self.current_time = self._base_time

    def trigger_sensor(
        self,
        sensor_id: str,
        state: bool = True,
        timestamp: float | None = None,
        delay: float | None = None,
    ) -> None:
        """Trigger sensor state change (ON/OFF).

        Args:
            sensor_id: The sensor entity ID
            state: True for ON, False for OFF
            timestamp: Explicit offset from base time (overrides delay)
            delay: Seconds to advance time before triggering
        """
        if delay is not None:
            self.current_time += delay
        if timestamp is not None:
            self.current_time = self._base_time + timestamp

        state_str = "on" if state else "off"

        # Update the sensor state first (this sets activated_at on OFF->ON transitions)
        if sensor_id in self.coordinator.sensors:
            sensor = self.coordinator.sensors[sensor_id]
            sensor.update_state(state, self.current_time)

        # Capture current area/sensor state for the snapshot
        areas_snapshot = {
            aid: {
                "occupancy": area.occupancy,
                "last_motion": area.last_motion,
            }
            for aid, area in self.coordinator.areas.items()
        }
        sensors_snapshot = {
            sid: {
                "state": sensor.current_state,
                "last_changed": sensor.last_changed,
            }
            for sid, sensor in self.coordinator.sensors.items()
        }

        snapshot = MapSnapshot(
            timestamp=self.current_time,
            event_type="sensor",
            description=f"sensor:{sensor_id}:{state_str}",
            areas=areas_snapshot,
            sensors=sensors_snapshot,
        )
        self.coordinator.occupancy_resolver.process_snapshot(
            snapshot,
            self.coordinator.areas,
            self.coordinator.sensors,
            self.coordinator.anomaly_detector,
        )

    def advance_time(self, delta: float) -> None:
        """Advance the simulated time."""
        self.current_time += delta


@pytest.fixture(autouse=True)
async def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations defined in the test dir."""
    return


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Return snapshot assertion fixture with the Home Assistant extension."""
    return snapshot.use_extension(HomeAssistantSnapshotExtension)


# Test markers for categorizing integration tests
def pytest_configure(config):
    """Register custom markers for integration tests."""
    config.addinivalue_line(
        "markers", "end_to_end: End-to-end integration test scenarios"
    )
    config.addinivalue_line("markers", "multi_sensor: Multi-sensor coordination tests")
    config.addinivalue_line("markers", "scenarios: Real-world scenario tests")
    config.addinivalue_line("markers", "edge_cases: Edge case and error scenario tests")
    config.addinivalue_line("markers", "anomaly: Anomaly detection integration tests")
    config.addinivalue_line("markers", "slow: Slow-running integration tests")
    config.addinivalue_line("markers", "integration: General integration tests")

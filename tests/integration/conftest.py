"""Configuration for integration tests."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion

# Import fixtures from test_fixtures to make them available to all integration tests
from .test_fixtures import (
    realistic_config,
    simple_config,
    multi_occupant_config,
    hass_with_realistic_config,
    hass_with_simple_config,
    hass_with_multi_occupant_config,
    coordinator_from_hass,
    sensor_helper,
    assert_occupancy_state,
    assert_warning_exists,
    assert_no_warnings,
)

# Re-export fixtures so pytest can discover them
__all__ = [
    "realistic_config",
    "simple_config",
    "multi_occupant_config",
    "hass_with_realistic_config",
    "hass_with_simple_config",
    "hass_with_multi_occupant_config",
    "coordinator_from_hass",
    "sensor_helper",
    "assert_occupancy_state",
    "assert_warning_exists",
    "assert_no_warnings",
    "snapshot",
]


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
    config.addinivalue_line(
        "markers", "multi_sensor: Multi-sensor coordination tests"
    )
    config.addinivalue_line("markers", "scenarios: Real-world scenario tests")
    config.addinivalue_line("markers", "edge_cases: Edge case and error scenario tests")
    config.addinivalue_line("markers", "anomaly: Anomaly detection integration tests")
    config.addinivalue_line("markers", "slow: Slow-running integration tests")
    config.addinivalue_line("markers", "integration: General integration tests")

"""Fixtures for Occupancy Tracker integration tests."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion

from custom_components.occupancy_tracker.const import DOMAIN

@pytest.fixture(autouse=True)
async def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations defined in the test dir."""
    return


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Return snapshot assertion fixture with the Home Assistant extension."""
    return snapshot.use_extension(HomeAssistantSnapshotExtension)


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry with default values."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Occupancy Tracker",
        data={
            "areas": {
                "living_room": {"name": "Living Room"},
                "kitchen": {"name": "Kitchen"},
            },
            "sensors": {
                "binary_sensor.motion_living_room": {
                    "area": "living_room",
                    "type": "motion",
                },
                "binary_sensor.motion_kitchen": {
                    "area": "kitchen",
                    "type": "motion",
                },
            },
            "adjacency": {
                "living_room": ["kitchen"],
                "kitchen": ["living_room"],
            },
        },
    )

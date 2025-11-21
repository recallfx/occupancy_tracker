"""Tests for button platform."""

import pytest
from unittest.mock import MagicMock, Mock

from homeassistant.core import HomeAssistant
from custom_components.occupancy_tracker.button import (
    ResetAnomaliesButton,
    async_setup_platform,
)
from custom_components.occupancy_tracker.coordinator import OccupancyCoordinator


@pytest.fixture
def coordinator():
    """Create a test occupancy coordinator."""
    hass = Mock(spec=HomeAssistant)
    config = {
        "areas": {"living_room": {}},
        "adjacency": {},
        "sensors": {},
    }
    return OccupancyCoordinator(hass, config)


class TestResetAnomaliesButton:
    """Test ResetAnomaliesButton class."""

    def test_create_button(self, coordinator):
        """Test creating a reset anomalies button."""
        button = ResetAnomaliesButton(coordinator)

        assert button._attr_name == "Reset Anomalies"
        assert button._attr_unique_id == "reset_anomalies_button"

    async def test_button_press(self, coordinator):
        """Test pressing the button resets anomalies."""
        # Create some warnings
        coordinator.anomaly_detector._create_warning("test1", "Test warning 1")
        coordinator.anomaly_detector._create_warning("test2", "Test warning 2")

        # Set up occupancy
        coordinator.area_manager.areas["living_room"].occupancy = 2

        assert len(coordinator.get_warnings()) == 2

        button = ResetAnomaliesButton(coordinator)

        # Press button
        await button.async_press()

        # Warnings should be cleared
        assert len(coordinator.get_warnings()) == 0

        # Occupancy should be preserved
        assert coordinator.area_manager.areas["living_room"].occupancy == 2

    async def test_button_press_multiple_times(self, coordinator):
        """Test pressing button multiple times doesn't cause errors."""
        button = ResetAnomaliesButton(coordinator)

        # Press multiple times
        await button.async_press()
        await button.async_press()
        await button.async_press()

        # Should not raise errors


class TestAsyncSetupPlatform:
    """Test async_setup_platform function."""

    async def test_setup_platform(self, hass):
        """Test setting up the button platform."""
        from custom_components.occupancy_tracker.const import DOMAIN

        # Create coordinator and add to hass.data
        config = {
            "areas": {"room1": {}},
            "adjacency": {},
            "sensors": {},
        }
        coordinator = OccupancyCoordinator(hass, config)

        hass.data[DOMAIN] = {"coordinator": coordinator}

        # Mock async_add_entities
        async_add_entities = MagicMock()

        # Call setup
        await async_setup_platform(hass, {}, async_add_entities)

        # Should create button
        assert async_add_entities.called
        buttons = async_add_entities.call_args[0][0]

        assert len(buttons) == 1
        assert isinstance(buttons[0], ResetAnomaliesButton)

    async def test_setup_platform_with_discovery_info(self, hass):
        """Test setup with discovery_info parameter."""
        from custom_components.occupancy_tracker.const import DOMAIN

        config = {
            "areas": {},
            "adjacency": {},
            "sensors": {},
        }
        coordinator = OccupancyCoordinator(hass, config)

        hass.data[DOMAIN] = {"coordinator": coordinator}

        async_add_entities = MagicMock()

        # Call with discovery_info (should be ignored)
        await async_setup_platform(hass, {}, async_add_entities, discovery_info={})

        assert async_add_entities.called

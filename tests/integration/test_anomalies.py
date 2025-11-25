"""
Anomaly detection and diagnostics integration tests.

Tests warning generation, resolution, and diagnostic reporting.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant

from custom_components.occupancy_tracker import DOMAIN
from .test_fixtures import SensorEventHelper


@pytest.mark.anomaly
class TestUnexpectedMotion:
    """Test unexpected motion detection."""

    async def test_first_motion_generates_warning(
        self, hass_with_simple_config: HomeAssistant
    ):
        """Motion without prior activity generates unexpected_motion warning."""
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        helper.trigger_motion("binary_sensor.motion_living")

        warnings = [w for w in coordinator.get_warnings() if w.is_active and w.type == "unexpected_motion"]
        assert len(warnings) >= 1

    async def test_adjacent_motion_no_warning(
        self, hass_with_simple_config: HomeAssistant
    ):
        """Motion from adjacent room doesn't generate new unexpected warning."""
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # First motion (will warn)
        helper.trigger_motion("binary_sensor.motion_living")
        
        # Adjacent motion (should NOT warn again)
        helper.trigger_motion("binary_sensor.motion_kitchen", delay=2)

        warnings = [w for w in coordinator.get_warnings() if w.is_active and w.type == "unexpected_motion"]
        assert len(warnings) <= 1  # Only first one

    async def test_exit_capable_no_warning(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """Exit-capable areas don't generate unexpected_motion warnings."""
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        helper.trigger_sensor("binary_sensor.person_front_left_camera", True)

        warnings = [
            w for w in coordinator.get_warnings()
            if w.is_active and w.type == "unexpected_motion" and w.area_id == "frontyard"
        ]
        assert len(warnings) == 0


@pytest.mark.anomaly
class TestTimeoutWarnings:
    """Test timeout-related warnings."""

    async def test_exit_area_auto_clears(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """Exit-capable areas auto-clear after 5 minutes."""
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        helper.trigger_sensor("binary_sensor.person_front_left_camera", True)
        assert coordinator.get_occupancy("frontyard") >= 1

        helper.advance_time(301)
        helper.check_timeouts()

        assert coordinator.get_occupancy("frontyard") == 0

    async def test_inactivity_timeout_24h(
        self, hass_with_simple_config: HomeAssistant
    ):
        """24 hours of inactivity clears occupancy."""
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        helper.trigger_motion("binary_sensor.motion_living")
        assert coordinator.get_occupancy("living_room") >= 1

        helper.advance_time(24 * 3600 + 1)
        helper.check_timeouts()

        assert coordinator.get_occupancy("living_room") == 0


@pytest.mark.anomaly
class TestWarningManagement:
    """Test warning accumulation and resolution."""

    async def test_warnings_accumulate(
        self, hass_with_simple_config: HomeAssistant
    ):
        """Multiple anomalies create multiple warnings."""
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Two unexpected motions in non-adjacent areas
        helper.trigger_motion("binary_sensor.motion_living")
        helper.trigger_motion("binary_sensor.motion_bedroom", delay=10)

        active = [w for w in coordinator.get_warnings() if w.is_active]
        assert len(active) >= 2

    async def test_reset_anomalies_clears_warnings(
        self, hass_with_simple_config: HomeAssistant
    ):
        """reset_anomalies() clears all warnings."""
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        helper.trigger_motion("binary_sensor.motion_living")
        helper.trigger_motion("binary_sensor.motion_bedroom", delay=10)

        coordinator.reset_anomalies()

        active = [w for w in coordinator.get_warnings() if w.is_active]
        assert len(active) == 0

    async def test_reset_anomalies_preserves_occupancy(
        self, hass_with_simple_config: HomeAssistant
    ):
        """reset_anomalies() keeps occupancy state."""
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        helper.trigger_motion("binary_sensor.motion_living")
        occ_before = coordinator.get_occupancy("living_room")

        if occ_before > 0:
            coordinator.reset_anomalies()
            assert coordinator.get_occupancy("living_room") == occ_before


@pytest.mark.integration
class TestSystemReset:
    """Test full system reset functionality."""

    async def test_full_reset_clears_all(
        self, hass_with_simple_config: HomeAssistant
    ):
        """Full reset clears occupancy and warnings."""
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        helper.trigger_motion("binary_sensor.motion_living")
        helper.trigger_motion("binary_sensor.motion_kitchen", delay=2)

        coordinator.reset()

        assert coordinator.get_occupancy("living_room") == 0
        assert coordinator.get_occupancy("kitchen") == 0
        assert len([w for w in coordinator.get_warnings() if w.is_active]) == 0

    async def test_reset_mid_journey(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """Reset during journey starts tracking fresh."""
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        helper.trigger_motion("binary_sensor.motion_entrance")
        helper.trigger_motion("binary_sensor.motion_front_hall", delay=2)

        coordinator.reset()

        helper.trigger_motion("binary_sensor.motion_back_hall", delay=2)

        assert coordinator.get_occupancy("entrance") == 0
        assert coordinator.get_occupancy("front_hall") == 0
        assert coordinator.get_occupancy("back_hall") >= 1


@pytest.mark.integration
class TestDiagnostics:
    """Test diagnostic reporting."""

    async def test_diagnose_returns_data(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """diagnose_motion_issues() returns sensor info."""
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        helper.trigger_motion("binary_sensor.motion_main_bedroom")
        helper.trigger_motion("binary_sensor.motion_living", delay=2)

        diag = coordinator.diagnose_motion_issues()
        assert diag is not None

    async def test_get_system_status(
        self, hass_with_realistic_config: HomeAssistant
    ):
        """get_system_status() returns comprehensive info."""
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        helper.trigger_motion("binary_sensor.motion_main_bedroom")

        status = coordinator.get_system_status()
        assert status is not None
        assert isinstance(status, dict)

    async def test_get_area_status_all_areas(
        self, hass_with_simple_config: HomeAssistant
    ):
        """get_area_status() works for all configured areas."""
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]

        for area_id in ["living_room", "kitchen", "bedroom"]:
            status = coordinator.get_area_status(area_id)
            assert status is not None


@pytest.mark.integration
class TestProbabilityCalculations:
    """Test occupancy probability calculations."""

    async def test_fresh_motion_high_probability(
        self, hass_with_simple_config: HomeAssistant
    ):
        """Fresh motion = probability 1.0."""
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        helper.trigger_motion("binary_sensor.motion_living")
        prob = coordinator.get_occupancy_probability("living_room", timestamp=helper.current_time)
        
        assert prob >= 0.9

    async def test_probability_decays_over_time(
        self, hass_with_simple_config: HomeAssistant
    ):
        """Probability decreases as time passes without motion."""
        coordinator = hass_with_simple_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        helper.trigger_motion("binary_sensor.motion_living")
        prob_fresh = coordinator.get_occupancy_probability("living_room", timestamp=helper.current_time)

        helper.advance_time(60 * 60)  # 1 hour
        prob_later = coordinator.get_occupancy_probability("living_room", timestamp=helper.current_time)

        assert prob_later < prob_fresh
        assert prob_later > 0.05  # Still non-zero

"""
Test masked movement scenarios where sensors stay ON.

Notation:
- Areas: Y=Frontyard, E=Entrance, F=Front Hall, B=Back Hall
- Motion sensor: + = active, (none) = inactive
- Occupancy: @ = occupied
- Door: | = closed, / = open
- Example: Y+@|EFB means Frontyard active+occupied, entry door closed, others empty
"""

import pytest
from homeassistant.core import HomeAssistant

from custom_components.occupancy_tracker import async_setup, DOMAIN
from tests.integration.test_fixtures import SensorEventHelper


@pytest.fixture
async def hass_with_realistic_config(hass: HomeAssistant, realistic_config: dict) -> HomeAssistant:
    """Provide configured Home Assistant instance."""
    result = await async_setup(hass, realistic_config)
    assert result is True
    return hass


class TestMaskedMovement:
    """Test masked movement where sensor stays ON, hiding passage."""

    async def test_masked_movement_chain(self, hass_with_realistic_config: HomeAssistant):
        """
        P1 moves to F and stays (sensor ON). P2 passes through F (masked) to B.
        
        Y|EFB                   # Initial: all empty, door closed
        Y+@|EFB                 # P1 detected outside
        Y+@/EFB                 # Door opens
        Y+/E+@FB                # P1 in entrance
        Y/EF+@B                 # P1 in F (sensor stays ON)
        Y+@|EF+@B               # P2 detected outside
        Y+@/EF+@B               # Door opens
        Y+/E+@F+@B              # P2 in entrance (F still active from P1)
        Y/E+@F+@B+@             # P2 in B (passed through F undetected)
        
        Bug: B pulls from F -> F becomes empty but active
        Fix: F refills from E via consistency resolution
        
        Expected: F@=1, B@=1, E@=0
        """
        coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
        helper = SensorEventHelper(coordinator)

        # Y+@|EFB - P1 outside
        helper.trigger_sensor("binary_sensor.person_front_left_camera", True)
        assert coordinator.get_occupancy("frontyard") == 1

        # Y+@/EFB - door opens/closes
        helper.trigger_sensor("binary_sensor.magnetic_entry", True, delay=0.5)
        helper.trigger_sensor("binary_sensor.magnetic_entry", False, delay=0.3)

        # Y+/E+@FB - P1 in entrance
        helper.trigger_sensor("binary_sensor.motion_entrance", True, delay=0.5)
        assert coordinator.get_occupancy("entrance") == 1

        # Y/EF+@B - P1 in F (sensor stays ON)
        helper.trigger_sensor("binary_sensor.motion_front_hall", True, delay=1)
        helper.trigger_sensor("binary_sensor.person_front_left_camera", False)
        helper.trigger_sensor("binary_sensor.motion_entrance", False)
        assert coordinator.get_occupancy("front_hall") == 1
        assert coordinator.get_occupancy("entrance") == 0

        # Y+@|EF+@B - P2 outside (F still active)
        helper.trigger_sensor("binary_sensor.person_front_left_camera", True, delay=5)

        # Y+@/EF+@B - door opens/closes
        helper.trigger_sensor("binary_sensor.magnetic_entry", True, delay=0.5)
        helper.trigger_sensor("binary_sensor.magnetic_entry", False, delay=0.3)

        # Y+/E+@F+@B - P2 in entrance
        helper.trigger_sensor("binary_sensor.motion_entrance", True, delay=0.5)
        assert coordinator.get_occupancy("entrance") == 1

        # P2 walks through F (MASKED - sensor already ON, no event)
        # Y/E+@F+@B+@ - P2 arrives in B
        helper.trigger_sensor("binary_sensor.motion_back_hall", True, delay=2)

        # Y/EF+@B+@ - consistency resolution refills F from E
        assert coordinator.get_occupancy("back_hall") == 1, "B should have P2"
        assert coordinator.get_occupancy("front_hall") == 1, "F should have P1"
        assert coordinator.get_occupancy("entrance") == 0, "E should be empty"

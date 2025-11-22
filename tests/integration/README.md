# Integration Tests

This directory contains comprehensive integration tests for the Occupancy Tracker Home Assistant custom component.

## Purpose

Integration tests verify that all components of the system work together correctly in realistic scenarios. Unlike unit tests which test individual components in isolation, these tests:

- Simulate complete user journeys through the house
- Test multi-sensor coordination and interactions
- Verify anomaly detection in realistic contexts
- Test complex multi-occupant scenarios
- Validate time-based behaviors and timeouts

## Test Organization

### Test Files

- **`test_end_to_end_scenarios.py`**: Complete person journeys, sleep scenarios, multi-room simultaneous events, and sensor lifecycle tests
- **`test_multi_sensor_coordination.py`**: Bridging sensors (magnetic doors), camera coordination, timing interactions, and multi-area sensors
- **`test_real_world_scenarios.py`**: Daily routines, multi-occupant scenarios, work-from-home patterns, visitor scenarios, and edge cases
- **`test_anomaly_integration.py`**: Long sensor activations, impossible appearances, suspicious transitions, and multi-anomaly scenarios
- **`test_diagnostics_reset.py`**: System diagnostics, reset functionality, and status queries

### Fixtures and Utilities

- **`test_fixtures.py`**: Comprehensive test fixtures and helper utilities
  - `realistic_config`: 8-area configuration based on actual config.yaml
  - `simple_config`: 3-room configuration for basic scenarios
  - `multi_occupant_config`: 6-room configuration optimized for multi-person testing
  - `SensorEventHelper`: Utility class for simulating sensor events
  - Helper functions: `assert_occupancy_state()`, `assert_warning_exists()`, etc.

- **`conftest.py`**: Integration test configuration and pytest markers

## Running Tests

### Run All Integration Tests
```bash
uv run pytest tests/integration/ -v
```

### Run Specific Test Categories

Using pytest markers:

```bash
# End-to-end scenarios
uv run pytest tests/integration/ -v -m end_to_end

# Multi-sensor coordination
uv run pytest tests/integration/ -v -m multi_sensor

# Real-world scenarios
uv run pytest tests/integration/ -v -m scenarios

# Anomaly detection
uv run pytest tests/integration/ -v -m anomaly

# Edge cases
uv run pytest tests/integration/ -v -m edge_cases
```

### Run Specific Test File
```bash
uv run pytest tests/integration/test_end_to_end_scenarios.py -v
```

### Run Specific Test
```bash
uv run pytest tests/integration/test_end_to_end_scenarios.py::TestPersonJourneys::test_entry_from_frontyard_to_living -v
```

## Test Scenarios Covered

### End-to-End Scenarios
- Person entering from frontyard through to living room
- Complex journeys through multiple connected rooms
- Exiting through exit-capable areas with auto-clear
- Reverse journeys (going back and forth)
- Sleep scenarios (extended periods without motion)
- Multi-room simultaneous activity
- Sensor availability and lifecycle

### Multi-Sensor Coordination
- Magnetic door sensors triggering transitions
- Multiple door crossings
- Camera person detection coordinating with motion sensors
- Rapid sequential sensor activations
- Overlapping sensor activations
- Bidirectional bridging sensor behavior

### Real-World Scenarios
- Morning routines (wake → bathroom → kitchen → living)
- Leaving and returning home
- Evening bedtime routines
- Two people moving independently (parallel paths)
- Family gathering and dispersing
- Work-from-home (all day in one room with breaks)
- Visitor scenarios (entering, staying, leaving)
- Quick room transitions vs slow movements

### Anomaly Detection
- Sensors stuck in ON state (>300s)
- Impossible appearances (motion without adjacent activity)
- Exit-capable areas (no impossible appearance warnings)
- Suspicious transitions between non-adjacent rooms
- Multiple anomalies simultaneously
- Anomaly reset functionality

### System Functions
- Complete diagnostics dumps
- Full system reset (clears everything)
- Reset anomalies only (preserves occupancy)
- System status queries
- Occupancy probability calculations over time

## Writing New Integration Tests

### 1. Choose the Right Test File

Add your test to the appropriate file based on what you're testing:
- Complete journeys → `test_end_to_end_scenarios.py`
- Sensor interactions → `test_multi_sensor_coordination.py`
- User scenarios → `test_real_world_scenarios.py`
- Anomaly behavior → `test_anomaly_integration.py`
- System functions → `test_diagnostics_reset.py`

### 2. Use Appropriate Fixtures

```python
async def test_my_scenario(self, hass_with_realistic_config: HomeAssistant):
    """Test description."""
    coordinator = hass_with_realistic_config.data[DOMAIN]["coordinator"]
    helper = SensorEventHelper(coordinator)
    
    # Your test code here
```

Choose from:
- `hass_with_realistic_config`: 8-area complex home
- `hass_with_simple_config`: 3-room simple setup
- `hass_with_multi_occupant_config`: 6-room multi-person setup

### 3. Simulate Events with SensorEventHelper

```python
# Trigger single sensor
helper.trigger_sensor("binary_sensor.motion_living", True, delay=2.0)

# Trigger motion (ON then OFF)
on_time, off_time = helper.trigger_motion("binary_sensor.motion_kitchen", 
                                         delay=2.0, duration=5.0)

# Simulate journey through multiple sensors
timestamps = helper.simulate_journey([
    "binary_sensor.motion_entrance",
    "binary_sensor.motion_living",
    "binary_sensor.motion_kitchen",
], interval=2.0)

# Advance time
helper.advance_time(300)  # 5 minutes

# Check timeouts
helper.check_timeouts()
```

### 4. Use Assertion Helpers

```python
# Assert occupancy state
assert_occupancy_state(coordinator, {
    "living_room": 1,
    "kitchen": 0,
    "bedroom": 0,
})

# Assert warning exists
assert_warning_exists(coordinator, "long_sensor_activation", 
                     "binary_sensor.motion_living")

# Assert no warnings
assert_no_warnings(coordinator)
```

### 5. Add Pytest Markers

```python
@pytest.mark.end_to_end
class TestMyScenarios:
    """Test my scenarios."""
    
    @pytest.mark.slow  # If test takes a long time
    async def test_long_running_scenario(self, ...):
        """Test description."""
        ...
```

## Tips for Effective Integration Tests

1. **Test realistic scenarios**: Base tests on actual user behaviors
2. **Use appropriate timing**: Match realistic sensor trigger intervals
3. **Test edge cases**: Include unusual but possible scenarios
4. **Verify state thoroughly**: Check occupancy, probabilities, and warnings
5. **Clean up**: Tests should be independent and not affect each other
6. **Document assumptions**: Explain expected behavior in docstrings
7. **Keep tests focused**: Each test should verify one specific scenario

## Coverage Goals

Integration tests should verify:
- ✅ Complete user journeys work end-to-end
- ✅ Sensors coordinate correctly across different types
- ✅ Anomaly detection works in realistic scenarios
- ✅ Multi-occupant tracking is accurate
- ✅ Time-based behaviors (decay, timeouts) work correctly
- ✅ System functions (diagnostics, reset) work with complex state
- ✅ Edge cases are handled gracefully

## Debugging Failed Tests

If an integration test fails:

1. **Check the test output** for assertion errors
2. **Run the test in verbose mode**: `pytest -vv`
3. **Add debug prints** to see intermediate state
4. **Check timing**: Ensure delays match expected behavior
5. **Verify sensor configuration**: Ensure fixtures have correct adjacency
6. **Review logs**: Check for warnings or errors in coordinator logic

## Performance Considerations

Integration tests can be slower than unit tests because they:
- Set up full Home Assistant instances
- Process multiple sensor events in sequence
- Simulate time passing and timeout checks

To maintain fast test suite:
- Keep tests focused and minimal
- Use simple configs when possible
- Mark slow tests with `@pytest.mark.slow`
- Run slow tests separately when needed

## Related Documentation

- [Main README](../../README.md) - Project overview and features
- [Unit Tests](../occupancy_tracker/README.md) - Component unit tests (if exists)
- [Implementation Plan](/.gemini/antigravity/brain/d568501b-ee12-45a5-8717-a38fbc6a59bd/implementation_plan.md) - Integration test design decisions

# AI Agent Instructions

## Architecture overview

This Home Assistant integration tracks occupancy across areas using a coordinator-based architecture. The core components are:

- `OccupancyCoordinator` (`coordinator.py`): The central hub that manages the system state, coordinates updates, and interfaces with Home Assistant. It uses `DataUpdateCoordinator` but triggers updates manually via `async_set_updated_data` when events occur.
- `AreaManager` (`area_manager.py`): Manages the state of individual areas (occupancy count, last motion, etc.).
- `SensorManager` (`sensor_manager.py`): Handles sensor state changes, maintains sensor history, and updates the `AreaManager`.
- `AnomalyDetector` (`helpers/anomaly_detector.py`): Monitors for anomalies like sensors getting stuck or inconsistent states.

The system is initialized in `__init__.py` via `async_setup`, which reads the YAML configuration and creates the `OccupancyCoordinator`.

## Critical patterns

**Sensor Event Processing**:
Sensor state changes are caught in `__init__.py` by `state_change_listener` and passed to `coordinator.process_sensor_event(sensor_id, state, timestamp)`. The coordinator then delegates to `SensorManager`.

**State Updates**:
Unlike a polling coordinator, this system is event-driven. `async_set_updated_data` is called explicitly in `process_sensor_event` and `check_timeouts` to notify listeners (sensors, buttons, etc.) of state changes.

**Anomaly Detection**:
The `AnomalyDetector` runs checks to identify issues. `check_timeouts` should be called periodically (or on events) to update time-dependent anomalies.

**Configuration**:
Configuration is strictly YAML-based (`config.yaml` style). There is no Config Flow (`config_flow.py`). The schema is defined in `__init__.py` using `voluptuous`.
- `areas`: Definitions of areas.
- `sensors`: Mapping of HA entities to areas and types.
- `adjacency`: Defining connections between areas.

## Testing commands

Run tests with `uv run pytest tests/`.
The tests use `pytest-homeassistant-custom-component`.
Tests should mirror the structure of the source code.

## Common pitfalls

- **Config Flow**: Do not attempt to use or reference `config_flow.py` or `async_step_user`. This integration uses `async_setup` in `__init__.py`.
- **Entity IDs**: Sensor keys in configuration are expected to be valid Home Assistant entity IDs (e.g., `binary_sensor.kitchen_motion`).
- **Coordinator Access**: The coordinator is stored in `hass.data[DOMAIN]["coordinator"]`.

## File organization

- `custom_components/occupancy_tracker/`: Main component code.
- `custom_components/occupancy_tracker/helpers/`: Helper classes (`types.py`, `warning.py`, etc.).
- `tests/`: Test files mirroring the component structure.

## Readme writing style

Write like a human, not an AI. Avoid flowery language, summary phrases, generic lists, vague statements, and common AI patterns. Use clear, accurate, and natural language with real-world detail and nuance.
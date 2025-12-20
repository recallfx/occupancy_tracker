# AI Agent Instructions

> **READ THIS FIRST**: This document contains critical context for working on this codebase. Review relevant sections before making changes. Update the "Session Log" section when you make significant decisions or discoveries.

## Architecture overview

Home Assistant integration for room presence detection using probabilistic state tracking. Event-driven, not polling.

**Core flow**: HA sensor events → `__init__.py:state_change_listener` → `coordinator.process_sensor_event()` → `MapOccupancyResolver.process_snapshot()` → state mutations → `async_set_updated_data()`

**Key components**:
- `OccupancyCoordinator` (`coordinator.py`): Owns all state (`self.areas`, `self.sensors`), orchestrates helpers.
- `MapOccupancyResolver` (`helpers/map_occupancy_resolver.py`): Stateless logic engine - processes snapshots, mutates AreaState in-place. Uses an **activation-window model** for movement.
- `AreaState` / `SensorState` (`helpers/`): Data models with occupancy counts, timestamps, activity history.
- `AnomalyDetector` (`helpers/anomaly_detector.py`): Generates warnings for stuck sensors, impossible movements, and timeouts.
- `MapStateRecorder`: Captures immutable snapshots for history replay and crash recovery.

**Key principle**: Occupancy is an integer counter. People move via adjacency map. Movement is only confirmed when a sensor turns OFF and a neighbor has a matching activation window.

## Configuration

YAML-only via `async_setup` in `__init__.py`. **No Config Flow**.

```yaml
occupancy_tracker:
  areas:
    living_room:
      name: "Living Room"
      exit_capable: false  # true for front doors, backyards
      indoors: true        # false for yards, porches
  adjacency:
    living_room: [kitchen, hallway]  # auto-bidirectional
  sensors:
    binary_sensor.living_room_motion:
      area: living_room  # or [area1, area2] for bridging sensors
      type: motion  # motion, magnetic, camera_motion, camera_person
```

Schema validated with voluptuous. Coordinator stored at `hass.data[DOMAIN]["coordinator"]`.

## Testing

```bash
uv run pytest tests/                    # all tests
uv run pytest tests/occupancy_tracker/  # unit tests
uv run pytest tests/integration/        # integration tests
uv run pytest -v -m end_to_end          # by marker
```

**Test organization**: Mirrors source structure. Unit tests in `tests/occupancy_tracker/`, integration in `tests/integration/`.

**Test patterns** (see `tests/integration/test_fixtures.py`):
- `SensorEventHelper` for triggering events with timestamps
- `assert_occupancy_state(coordinator, {"living": 1, "kitchen": 0})`
- Fixtures: `hass_with_realistic_config`, `hass_with_simple_config`

**Unit test pattern**: Mock `HomeAssistant`, pass config dict directly to `OccupancyCoordinator(hass, config)`.

## Critical patterns

**Motion-ON**: Mark area occupied immediately (leading activation). Check adjacent areas for "plausible source" (occupied or active). If none found, flag anomaly (e.g., `no_adjacent_source`) but still add occupancy.

**Motion-OFF**: Person STAYS unless an adjacent sensor activated *after* this area turned ON and *before/at* this area turned OFF. If valid neighbor(s) found, move occupancy (clear source, mark targets). Supports multi-hop through active paths.

**Consistency resolution**: Periodic consistency checks are **disabled** in the lean architecture. Logic is purely event-driven.

**Probability decay**: 100% → 90% → exponential decay to 10% over ~1 hour. Formula in `get_occupancy_probability()`.

## Simulation

Interactive web UI for testing: `python -m simulation.server` then open http://localhost:8080

Uses `SimOccupancyCoordinator` wrapping the real coordinator, loads from `config.yaml`.

## Common pitfalls

- Don't poll - system is event-driven. Use `async_set_updated_data()` after state changes.
- Adjacency is auto-bidirectional.
- `exit_capable` areas auto-clear after 5min.
- `indoors` defaults to true; set false for outdoor areas to improve anomaly detection.
- Sensor entity IDs must match HA format (`binary_sensor.xyz`).
- State is mutable - `MapOccupancyResolver` modifies `AreaState` objects directly.

## Writing style

Write like a human. Avoid flowery language, summary phrases, vague statements, and common AI patterns. Be direct and specific.

---

## Session Log

Document significant decisions, findings, and context that future sessions need to know. Most recent entries first.

### 2025-12-20: Activation-Window Refactor
- Refactored `MapOccupancyResolver` to use an activation-window model.
- Movement now happens on **Motion-OFF** if a neighbor activated after the source turned ON.
- **Motion-ON** now only records entry and checks for plausible sources (anomalies).
- Periodic consistency checks disabled to simplify logic and improve predictability.
- Added `indoors` config for areas to better detect outdoor-to-indoor intrusions.

### 2025-12-20: Simulation reset control
- Added simulation reset command via WebSocket and UI button in the simulator header
- Reset flow clears backend areas/sensors/history and resets local draggable people/input system (exits history mode first)
- Use the "Reset State" button (requires active WS connection)

### 2024-11-26: Instructions file created
- Established architecture documentation with core flow, components, and patterns
- Key insight: `MapOccupancyResolver` is stateless and mutates `AreaState` in-place
- The old `AreaManager`/`SensorManager` classes no longer exist - coordinator owns state directly
- Motion-OFF logic is critical: person STAYS by default, only moves with explicit evidence

### Template for new entries
```
### YYYY-MM-DD: Brief title
- What was decided/discovered
- Why it matters
- Any gotchas or follow-ups
```
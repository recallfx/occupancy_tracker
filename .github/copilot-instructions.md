# AI Agent Instructions

> **READ THIS FIRST**: This document contains critical context for working on this codebase. Review relevant sections before making changes. Update the "Session Log" section when you make significant decisions or discoveries.

## Architecture overview

Home Assistant integration for room presence detection using probabilistic state tracking. Event-driven, not polling.

**Core flow**: HA sensor events → `__init__.py:state_change_listener` → `coordinator.process_sensor_event()` → `MapOccupancyResolver.process_snapshot()` → state mutations → `async_set_updated_data()`

**Key components**:
- `OccupancyCoordinator` (`coordinator.py`): Owns all state (`self.areas`, `self.sensors`), orchestrates helpers
- `MapOccupancyResolver` (`helpers/map_occupancy_resolver.py`): Stateless logic engine - processes snapshots, mutates AreaState in-place
- `AreaState` / `SensorState` (`helpers/`): Data models with occupancy counts, timestamps, activity history
- `AnomalyDetector` (`helpers/anomaly_detector.py`): Generates warnings for stuck sensors, impossible movements
- `MapStateRecorder`: Captures immutable snapshots for history replay and crash recovery

**Key principle**: Occupancy is an integer counter (supports multiple people), not boolean. People can only move via adjacency map - no teleportation.

## Configuration

YAML-only via `async_setup` in `__init__.py`. **No Config Flow** - don't reference `config_flow.py` or `async_step_user`.

```yaml
occupancy_tracker:
  areas:
    living_room:
      name: "Living Room"
      exit_capable: false  # true for front doors, backyards
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

**Motion-ON**: Find occupied adjacent area → move occupant. If none found and `exit_capable`, add new person. Otherwise flag anomaly but still add (lights must work).

**Motion-OFF**: Person STAYS unless adjacent sensor activated within 5s (explicit move) or is active AND occupied (masked movement). Don't move based on stale activations.

**Consistency resolution**: `resolve_consistency()` runs after events; `resolve_consistency_periodic()` runs every 5s to handle edge cases where areas are active but empty.

**Probability decay**: 100% → 90% → exponential decay to 10% over ~1 hour. Formula in `get_occupancy_probability()`.

## Simulation

Interactive web UI for testing: `python -m simulation.server` then open http://localhost:8080

Uses `SimOccupancyCoordinator` wrapping the real coordinator, loads from `config.yaml`.

## Common pitfalls

- Don't poll - system is event-driven. Use `async_set_updated_data()` after state changes
- Adjacency is auto-bidirectional; defining `A → B` implies `B → A`
- `exit_capable` areas (doors, yards) auto-clear after 5min and allow "entry from outside"
- Sensor entity IDs must match HA format (`binary_sensor.xyz`)
- State is mutable - `MapOccupancyResolver` modifies `AreaState` objects directly

## Writing style

Write like a human. Avoid flowery language, summary phrases, vague statements, and common AI patterns. Be direct and specific.

---

## Session Log

Document significant decisions, findings, and context that future sessions need to know. Most recent entries first.

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
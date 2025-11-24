# Occupancy Tracker - Architecture & Business Logic Analysis

## Executive Summary

The **Occupancy Tracker** is a sophisticated, event-driven Home Assistant integration designed to track room occupancy using a probabilistic state machine. Unlike simple binary motion-to-occupancy automations, it maintains a persistent state of "occupants" moving between defined areas, validated by an adjacency map.

## 1. Architecture Overview

The system follows a **Coordinator-Helper** pattern, centered around a `DataUpdateCoordinator` that directly manages state.

### 1.1 Core Components

#### **`OccupancyCoordinator` (Central Hub)**
- **Location**: `coordinator.py`
- **Role**: Orchestrates the entire system and manages state
- **Responsibilities**:
  - **State Management**: Directly owns `areas` (Dict[str, AreaState]) and `sensors` (Dict[str, SensorState])
  - **Event Processing**: Validates sensor events, updates sensor state, records snapshots
  - **Orchestration**: Coordinates `MapOccupancyResolver`, `AnomalyDetector`, and `MapStateRecorder`
  - **Derived Metrics**: Calculates **Occupancy Probability** with time-based decay
  - **Timeouts**: Handles `check_timeouts` for auto-clear and stale state detection
  - **Diagnostics**: Provides status information and stuck sensor detection
  - **Reset Operations**: Manages system resets and warning resolution
  - **History Replay**: Rebuilds state from recorded snapshots
  - **Home Assistant Integration**: Exposes data via `async_set_updated_data`

#### **`MapOccupancyResolver` (Logic Engine)**
- **Location**: `helpers/map_occupancy_resolver.py`
- **Role**: The "brain" of the system - pure logic component
- **Responsibilities**:
  - Takes a `MapSnapshot` and determines how it affects `AreaState`
  - Enforces the rules of physics defined by the system (e.g., "people cannot teleport")
  - Validates transitions against adjacency map
  - Implements the state machine logic for occupancy changes
  - Supports history replay for crash recovery
  - **Design Principle**: Stateless business logic - accepts data structures, returns nothing (mutates in-place)

#### **`AnomalyDetector` (Health Check)**
- **Location**: `helpers/anomaly_detector.py`
- **Role**: Sidecar process for system health
- **Responsibilities**:
  - Observes the state for irregularities
  - Detects stuck sensors, impossible movements
  - Generates `Warning` objects for issues
  - Manages warning lifecycle (creation, resolution, clearing)

#### **State Objects (Data Models)**
- **`AreaState`**: Individual area state (occupancy count, last motion, activity history)
- **`SensorState`**: Individual sensor state (current state, reliability, history)
- **`MapSnapshot`**: Immutable snapshot of system state at a point in time

## 2. Business Logic & Algorithms

### 2.1 Occupancy State Machine

The system treats occupancy as a **counter (integer)**, not a boolean. This allows tracking multiple occupants in the same area.

#### Entry (Motion ON)

When motion is detected in an area, the resolver evaluates the situation:

1. **Already Occupied**: No change to count. Update `last_motion` timestamp.

2. **Empty Area**: The resolver checks neighbors defined in `adjacency`:
   - **Valid Move**: If a neighbor is occupied and had recent activity (within 120s) or recent deactivation, occupancy moves:
     - Neighbor area: -1 occupant
     - Target area: +1 occupant
   
   - **Entry from Outside**: If the area is `exit_capable` (e.g., Front Hall, Backyard):
     - Target area: +1 occupant (new person entering the system)
   
   - **Anomaly**: If neither above is true:
     - System forces occupancy (Target +1) to ensure lights turn on
     - Flags a warning for "Unexpected Motion"

#### Exit (Motion OFF)

Motion clearing does **not** immediately clear occupancy:
- Updates the "last active" timestamp
- Stores deactivation in recent history (last 3 deactivations per area)
- Occupancy is only cleared by:
  - Moving to another room (validated transition)
  - Timeout conditions (see section 2.3)

### 2.2 Probabilistic Decay

Occupancy is not binary; it has a **confidence score** that decays over time.

The `get_occupancy_probability` method implements:

- **0 - 60s**: **100% (1.0)** confidence - person definitely present
- **1 - 5 min**: **90% (0.9)** confidence - high confidence of presence
- **> 5 min**: **Exponential Decay**
  - Formula: $P(t) = 0.1 + 0.8 \cdot e^{-k(t-300)}$ where $k \approx 0.00021$
  - Decays from 0.9 down to 0.1 over ~1 hour
  - This handles "sedentary" scenarios (reading, watching TV, sleeping) where motion stops but presence is likely

**Design Rationale**: The probability decay allows the system to maintain presence awareness during extended periods without motion while still signaling decreasing confidence. This is critical for bedroom scenarios where people may sleep for 8+ hours.

### 2.3 Timeouts & Cleanup

#### Exit-Capable Auto-Clear
If an area is marked `exit_capable` (e.g., Garage, Front Door, Backyard):
- **5 minutes** of no motion triggers auto-clear
- Assumes the person left the house/system
- Creates a warning for tracking purposes

#### Stale State Reset
For all areas:
- **12 Hours**: Warning issued for "Extended Occupancy" (potential false positive)
- **24 Hours**: Hard reset of the area occupancy to 0 (prevents infinite stale states)

### 2.4 Sensor Types & Behaviors

#### Motion Sensors
- **Types**: `motion`, `camera_motion`, `camera_person`
- **Activation**: Triggers occupancy evaluation (entry logic)
- **Deactivation**: Records in history, doesn't clear occupancy

#### Magnetic Sensors
- **Type**: `magnetic`
- **Configuration**: Bridges two areas via `between_areas` or `area: [area1, area2]`
- **Behavior**: Opening a door/window records motion in both bridged areas
- **Use Case**: Validates transitions between rooms with physical barriers

#### Multi-Area (Bridging) Sensors
- Sensors can be assigned to multiple areas: `area: [room1, room2]`
- Commonly used for doorways between rooms
- Records motion in all assigned areas simultaneously

### 2.5 Snapshot Replayability

A unique architectural feature is the **`MapStateRecorder`**.

#### Recording
Every event creates a `MapSnapshot` containing:
- Timestamp
- Event type (sensor activation/deactivation)
- Sensor ID and new state
- Prior state of all areas
- Prior state of all sensors

#### Benefits
1. **Crash Recovery**: Rebuild state after a crash or code reload
2. **Debugging**: Replay history to understand complex race conditions
3. **Auditing**: Complete audit trail of all state changes
4. **Testing**: Deterministic replay for integration tests

#### Implementation
- `recalculate_from_history`: Replays all snapshots to rebuild state
- `rebuild_from_history`: Public API in SensorManager

## 3. Data Flow

### 3.1 Event Processing Flow

1. **Event**: Home Assistant fires `state_changed` for `binary_sensor.kitchen_motion`
2. **Ingest**: `__init__.py:state_change_listener` receives event → `Coordinator.process_sensor_event`
3. **Validate**: `Coordinator` checks if sensor is known and updates `SensorState`
4. **Record**: `Coordinator` creates `MapSnapshot` via `MapStateRecorder`
   - Captures: Timestamp + Sensor State + Current Area Occupancy
5. **Resolve**: `MapOccupancyResolver.process_snapshot` analyzes:
   - *Is Kitchen adjacent to Living Room?* → Check adjacency map
   - *Is Living Room occupied?* → Check AreaState
   - *Was there recent activity in Living Room?* → Check motion history
   - *Decision*: Move occupant Living Room → Kitchen
   - *Update*: Directly mutates `AreaState` objects (occupancy counts, timestamps)
6. **Post-Process**: `Coordinator` refreshes snapshot state and checks for stuck sensors
7. **Notify**: `Coordinator` calls `async_set_updated_data`, triggering HA entity updates

**Key Simplification**: Reduced from 9 steps to 7 steps by eliminating intermediate manager hops.

### 3.2 Timeout Processing Flow

Periodically (triggered by various events or external scheduler):

1. **Trigger**: `Coordinator.check_timeouts` called
2. **Decay**: Probability scores recalculated for all areas
3. **Exit Check**: Exit-capable areas checked for 5-minute timeout
4. **Stale Check**: All areas checked for 12h/24h timeouts
5. **Record**: Snapshot may be recorded for audit trail
6. **Notify**: `async_set_updated_data` updates all entities

## 4. Configuration Schema

### 4.1 Areas
```yaml
areas:
  area_id:
    name: "Human Readable Name"
    exit_capable: true/false  # Optional, default false
```

### 4.2 Adjacency Map
```yaml
adjacency:
  area_id: [adjacent_area_1, adjacent_area_2, ...]
```

**Note**: The adjacency map is automatically bidirectional. If `room_a: [room_b]` is defined, `room_b → room_a` is also valid.

### 4.3 Sensors
```yaml
sensors:
  sensor_entity_id:
    area: room_id  # Single area
    # OR
    area: [room_id1, room_id2]  # Bridging sensor
    type: motion | magnetic | camera_motion | camera_person
```

## 5. Entity Types Provided

### 5.1 Binary Sensors
- **Occupancy Sensors**: `binary_sensor.occupancy_tracker_{area_id}`
  - State: ON when occupancy > 0
  - Attributes: occupancy count, last motion time

### 5.2 Numeric Sensors
- **Probability Sensors**: `sensor.occupancy_tracker_{area_id}_probability`
  - Value: 0.0 - 1.0 (confidence score)
  - Updates in real-time with decay

### 5.3 Text Sensors
- **Warning Sensors**: `sensor.occupancy_tracker_warnings`
  - Lists active anomalies/warnings
  - JSON array of warning objects

### 5.4 Buttons
- **Reset Warnings**: Clears all active warnings
- **Reset System**: Full reset (occupancy + warnings + sensors)

## 6. Key Design Patterns

### 6.1 Event-Driven Architecture
- No polling; system reacts only to events
- `update_interval=None` in coordinator
- Manual `async_set_updated_data` calls

### 6.2 Immutable Snapshots
- State changes recorded as immutable snapshots
- Enables replay and auditing
- Separates recording from processing

### 6.3 Separation of Concerns
- **Coordinator**: State management + orchestration (owns state, coordinates helpers)
- **MapOccupancyResolver**: Pure business logic (snapshots → state changes, stateless)
- **AnomalyDetector**: Health monitoring (observes and warns)
- **State Objects**: Data models (`AreaState`, `SensorState`, `MapSnapshot`)

### 6.4 Validation by Adjacency
- All transitions must be physically plausible
- Adjacency map defines valid movements
- Violations flagged but don't break the system

## 7. Handling Special Cases

### 7.1 Sleep Scenarios
- System maintains occupancy during 8+ hours without motion
- Probability decays to 0.1 but occupancy count remains
- Occupancy only cleared by actual movement or 24h timeout

### 7.2 Multi-Occupant Homes
- Integer counters support multiple people in same area
- Tracks "occupant units" not individuals
- Example: 2 people in bedroom, 1 moves → bedroom=1, destination=1

### 7.3 Simultaneous Motion
- Multiple sensors can trigger simultaneously
- Each processed independently with timestamp ordering
- Resolver handles race conditions via state snapshot

### 7.4 Stuck Sensors
- Detected when sensor stays active for extended period (default 300s)
- Marked as unreliable
- Warning generated for user attention
- System continues to function

### 7.5 Impossible Appearances
- Motion in non-adjacent area without prior presence
- System allows occupancy (lights turn on) but flags warning
- Exit-capable areas exempt from this check

## 8. Testing Strategy

### 8.1 Unit Tests (`tests/occupancy_tracker/`)
- Test individual components in isolation
- Mock dependencies
- Fast execution, high coverage

### 8.2 Integration Tests (`tests/integration/`)
- Test complete system behavior
- Realistic scenarios: sleep, multi-occupant, daily routines
- Snapshot replay validation
- End-to-end event processing

### 8.3 Test Organization
- Mirror source code structure
- Separate unit from integration tests
- Use pytest markers for categorization

## 9. Key Files Reference

| File | Purpose |
|------|---------|
| `__init__.py` | HA integration setup, event listener registration |
| `coordinator.py` | Central orchestration + state management, DataUpdateCoordinator implementation |
| `helpers/map_occupancy_resolver.py` | Core transition logic, state machine (stateless) |
| `helpers/anomaly_detector.py` | Health monitoring, warning generation |
| `helpers/map_state_recorder.py` | Snapshot recording and history |
| `helpers/area_state.py` | Individual area state model |
| `helpers/sensor_state.py` | Individual sensor state model |
| `helpers/warning.py` | Warning/anomaly data model |
| `diagnostics.py` | System diagnostics and status reporting |

## 10. Future Considerations

### 10.1 Potential Enhancements
- Machine learning for personalized decay curves
- Sensor reliability scoring based on historical accuracy
- Integration with person detection (cameras)
- Mobile app presence integration
- Zone-based grouping of areas

### 10.2 Known Limitations
- No individual person tracking (by design)
- Requires complete sensor coverage
- Accuracy depends on adjacency map correctness
- Cannot detect people who don't trigger sensors

## 11. Debugging Tips

### 11.1 Common Issues
- **Lights not turning on**: Check for "Unexpected Motion" warnings
- **Occupancy stuck**: Check for stuck sensor warnings, verify timeout settings
- **Erratic behavior**: Review snapshot history via diagnostics
- **Missing transitions**: Verify adjacency map is bidirectional

### 11.2 Diagnostic Tools
- `diagnose_motion_issues(sensor_id)`: Analyze why motion isn't detected
- `get_system_status()`: Full system state dump
- `get_area_status(area_id)`: Detailed area information
- Snapshot history in `MapStateRecorder`

## 12. Philosophy & Design Principles

1. **Preserve Intent**: If someone turns on a light, keep it on until they move elsewhere
2. **Fail Safe**: Anomalies generate warnings but don't break functionality
3. **Observable**: Rich diagnostics and history for troubleshooting
4. **Deterministic**: Same input history always produces same output state
5. **Realistic**: Model physical constraints (adjacency, time-of-travel)
6. **Gradual Confidence**: Use probability decay rather than binary states
7. **Human-Centric**: Optimize for common human behaviors (sleep, reading, etc.)

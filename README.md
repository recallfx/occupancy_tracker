# Occupancy Tracker [![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

A sophisticated Home Assistant integration for reliable room presence detection using probabilistic state tracking and anomaly detection.

## Features

- **Smart Occupancy Tracking**: Maintains accurate room presence even during sleep or sedentary activities
- **Multi-Area Support**: Track occupancy across interconnected rooms with adjacency validation
- **Probability Confidence**: Dynamic scoring that decays over time (100% → 10% over 1 hour)
- **Multiple Occupants**: Handles families and multi-person scenarios
- **Exit Detection**: Automatic clearing for areas where people can leave the system (front door, backyard)
- **Flexible Sensors**: Motion, magnetic (door/window), and camera detection
- **Anomaly Detection**: Alerts for stuck sensors and unusual patterns
- **Crash Recovery**: Rebuilds state from event history after restarts

## Quick Start

Add to your `configuration.yaml`:

```yaml
occupancy_tracker:
  areas:
    living_room:
      name: "Living Room"
    kitchen:
      name: "Kitchen"
    front_door:
      name: "Front Door"
      exit_capable: true  # People can leave the system from here
  
  adjacency:
    living_room: [kitchen, front_door]
    kitchen: [living_room]
    front_door: [living_room]
  
  sensors:
    binary_sensor.living_room_motion:
      area: living_room
      type: motion
    binary_sensor.kitchen_motion:
      area: kitchen
      type: motion
    binary_sensor.front_door:
      area: [front_door, living_room]  # Bridging sensor
      type: magnetic
```

## Installation

### Via HACS (Recommended)

1. Open HACS → Integrations
2. Click "Explore & Download Repositories"
3. Search for "Occupancy Tracker"
4. Download and restart Home Assistant
5. Add configuration to `configuration.yaml` (see Quick Start)

### Manual Installation

1. Download the [latest release](https://github.com/recallfx/occupancy_tracker/releases)
2. Extract to `custom_components/occupancy_tracker`
3. Restart Home Assistant
4. Add configuration to `configuration.yaml`

## Configuration Reference

### Areas

Define all rooms/spaces you want to track:

```yaml
areas:
  area_id:
    name: "Display Name"
    exit_capable: false  # Optional: set true for entry/exit points
```

**Exit-capable areas** (front door, backyard, etc.) automatically clear after 5 minutes of inactivity.

### Adjacency Map

Define which areas are physically connected:

```yaml
adjacency:
  living_room: [kitchen, hallway]
  kitchen: [living_room, dining_room]
  hallway: [living_room, bedroom]
```

The system automatically makes connections bidirectional.

### Sensors

Map your Home Assistant sensors to areas:

```yaml
sensors:
  binary_sensor.living_room_motion:
    area: living_room
    type: motion
  
  binary_sensor.front_door:
    area: [entryway, front_porch]  # Bridging sensor
    type: magnetic
```

**Supported sensor types:**
- `motion`: Standard motion sensors
- `magnetic`: Door/window contacts
- `camera_motion`: Camera motion detection
- `camera_person`: Camera person detection

## Entities Created

For each configured area, the integration creates:

- `binary_sensor.occupancy_tracker_{area_id}` - ON when occupied
- `sensor.occupancy_tracker_{area_id}_probability` - Confidence score (0.0-1.0)

System-wide entities:

- `sensor.occupancy_tracker_warnings` - Active anomaly alerts
- `button.occupancy_tracker_reset_warnings` - Clear warnings
- `button.occupancy_tracker_reset_system` - Full system reset

## How It Works

The system uses a probabilistic state machine:

1. **Motion detected** → Checks adjacent rooms for recent activity
2. **Valid transition** → Moves occupant count between rooms
3. **Confidence decay** → Probability drops over time without motion
4. **Exit detection** → Auto-clears exit-capable areas after 5 min
5. **Anomaly alerts** → Flags impossible movements or stuck sensors

For technical details, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Troubleshooting

**Lights not turning on?**
- Check for "Unexpected Motion" warnings in `sensor.occupancy_tracker_warnings`
- Verify the area is in your adjacency map
- Ensure adjacent areas have sensors

**Occupancy stuck?**
- Look for stuck sensor warnings
- Check if the area is exit-capable (should auto-clear after 5 min)
- Use the reset button to clear stale state

**Erratic behavior?**
- Review your adjacency map (are all connections defined?)
- Check sensor entity IDs match your configuration
- Enable debug logging: `logger: custom_components.occupancy_tracker: debug`

## Development

### Setup

```bash
# Clone repository
git clone https://github.com/recallfx/occupancy_tracker.git
cd occupancy_tracker

# Install dependencies (requires uv)
uv sync
```

### Running Tests

```bash
# All tests
uv run pytest tests/ -v

# Unit tests only
uv run pytest tests/occupancy_tracker/ -v

# Integration tests only
uv run pytest tests/integration/ -v

# With coverage
uv run pytest --cov=custom_components.occupancy_tracker
```

See [tests/integration/README.md](tests/integration/README.md) and [ARCHITECTURE.md](ARCHITECTURE.md) for more details.

## Contributing

Contributions welcome! Please:
1. Open an issue to discuss major changes
2. Follow existing code style (ruff formatting)
3. Add tests for new features
4. Update documentation as needed

## License

MIT License - see [LICENSE](LICENSE) file

## Credits

Built for the Home Assistant community
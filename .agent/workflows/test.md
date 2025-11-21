---
description: Run tests using uv
---

# Running Tests

Use the command below to run the test suite:

```bash
uv run pytest
```

2. Run a specific test file:
```bash
uv run pytest tests/occupancy_tracker/test_sensor.py
```

3. Run a specific test function:
```bash
uv run pytest tests/occupancy_tracker/test_sensor.py::test_context_clobbering_race_condition
```
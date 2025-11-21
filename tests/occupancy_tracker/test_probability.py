import pytest
import time
from custom_components.occupancy_tracker.area_manager import AreaManager
from custom_components.occupancy_tracker.helpers.area_state import AreaState

@pytest.fixture
def area_manager():
    config = {
        "areas": {
            "living_room": {"name": "Living Room"},
            "kitchen": {"name": "Kitchen"}
        }
    }
    return AreaManager(config)

def test_probability_decay(area_manager):
    area_id = "living_room"
    start_time = 1000.0
    
    # Initially empty
    assert area_manager.get_occupancy_probability(area_id, start_time) == 0.0
    
    # Record entry and motion
    area_manager.record_entry(area_id, start_time)
    area_manager.record_motion(area_id, start_time)
    
    # Check immediate probability (0-60s)
    assert area_manager.get_occupancy_probability(area_id, start_time + 10) == 1.0
    assert area_manager.get_occupancy_probability(area_id, start_time + 59) == 1.0
    
    # Check medium probability (1-5 mins)
    assert area_manager.get_occupancy_probability(area_id, start_time + 61) == 0.9
    assert area_manager.get_occupancy_probability(area_id, start_time + 299) == 0.9
    
    # Check decay (> 5 mins)
    # At 5 mins + 1 sec, it should be just below 0.9
    prob_start_decay = area_manager.get_occupancy_probability(area_id, start_time + 301)
    assert 0.8 < prob_start_decay <= 0.9
    
    # At 30 mins (1800s total, 1500s decay)
    # P = 0.1 + 0.8 * exp(-0.00021 * 1500)
    # P = 0.1 + 0.8 * 0.729 = 0.1 + 0.58 = 0.68
    prob_30_mins = area_manager.get_occupancy_probability(area_id, start_time + 1800)
    assert 0.6 < prob_30_mins < 0.8
    
    # At 60 mins (3600s total, 3300s decay)
    # P = 0.1 + 0.8 * exp(-0.00021 * 3300)
    # P = 0.1 + 0.8 * 0.5 = 0.5
    prob_60_mins = area_manager.get_occupancy_probability(area_id, start_time + 3600)
    assert 0.45 < prob_60_mins < 0.55
    
    # New motion should reset probability
    area_manager.record_motion(area_id, start_time + 4000)
    assert area_manager.get_occupancy_probability(area_id, start_time + 4001) == 1.0

def test_probability_zero_occupancy(area_manager):
    area_id = "living_room"
    start_time = 1000.0
    
    # Record motion but no entry (occupancy 0)
    area_manager.record_motion(area_id, start_time)
    
    # Should be 0 because occupancy is 0
    assert area_manager.get_occupancy_probability(area_id, start_time) == 0.0

def test_unknown_area(area_manager):
    assert area_manager.get_occupancy_probability("unknown_area") == 0.0

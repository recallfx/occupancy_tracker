# Define layout for visualization
import copy

BASE_LAYOUT = {
    "dimensions": {"width": 600, "height": 500},
    "areas": [
        {"id": "frontyard", "x": 0, "y": 0, "w": 600, "h": 100, "color": "#e0f7fa"},
        {"id": "entrance", "x": 0, "y": 100, "w": 150, "h": 150, "color": "#fff9c4"},
        {"id": "front_hall", "x": 150, "y": 100, "w": 150, "h": 150, "color": "#fff9c4"},
        {"id": "back_hall", "x": 300, "y": 100, "w": 150, "h": 150, "color": "#fff9c4"},
        {"id": "main_bedroom", "x": 450, "y": 100, "w": 150, "h": 150, "color": "#ffe0b2"},
        {"id": "main_bathroom", "x": 450, "y": 250, "w": 150, "h": 150, "color": "#e1bee7"},
        {"id": "living", "x": 0, "y": 250, "w": 300, "h": 150, "color": "#c8e6c9"},
        {"id": "backyard", "x": 0, "y": 400, "w": 600, "h": 100, "color": "#a5d6a7"},
    ],
    "sensors": [
        {"id": "motion_entrance", "x": 75, "y": 175, "type": "motion", "area": "entrance"},
        {"id": "motion_front_hall", "x": 225, "y": 175, "type": "motion", "area": "front_hall"},
        {"id": "motion_back_hall", "x": 375, "y": 175, "type": "motion", "area": "back_hall"},
        {"id": "motion_main_bedroom", "x": 525, "y": 175, "type": "motion", "area": "main_bedroom"},
        {"id": "motion_main_bathroom", "x": 525, "y": 325, "type": "motion", "area": "main_bathroom"},
        {"id": "motion_living", "x": 150, "y": 325, "type": "motion", "area": "living"},
        
        # Magnetic sensors (doors)
        {"id": "magnetic_entry", "x": 75, "y": 100, "type": "magnetic", "area": ["entrance", "frontyard"]}, # Entrance <-> Frontyard
        {"id": "magnetic_therace", "x": 75, "y": 400, "type": "magnetic", "area": ["entrance", "backyard"]}, # Entrance <-> Backyard (Assuming 'therace' is terrace/back)
        
        # Cameras
        {"id": "person_front_left_camera", "x": 100, "y": 50, "type": "camera_person", "area": "frontyard"},
        {"id": "person_back_left_camera", "x": 100, "y": 450, "type": "camera_person", "area": "backyard"},
    ],
    "connections": []
}


def build_layout(config):
    """Return layout data augmented with adjacency connections from config."""
    layout = copy.deepcopy(BASE_LAYOUT)
    adjacency = config.get("adjacency", {}) if isinstance(config, dict) else {}

    areas_by_id = {area["id"]: area for area in layout.get("areas", [])}
    seen_edges = set()
    connections = []

    for area_id, neighbors in adjacency.items():
        if area_id not in areas_by_id:
            continue
        for neighbor_id in neighbors:
            if neighbor_id not in areas_by_id:
                continue
            edge = tuple(sorted((area_id, neighbor_id)))
            if edge in seen_edges:
                continue
            seen_edges.add(edge)
            connections.append({"source": area_id, "target": neighbor_id})

    layout["connections"] = connections
    return layout

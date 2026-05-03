#!/usr/bin/env python3
"""
GeoJSON Exporter for Eternal Arcadia Map Data

Exports nodes, routes, and hazards to GeoJSON format for use in GIS tools.
Coordinates use the internal x/y system (0-10000) directly as GeoJSON coordinates.
"""

import json
import sys
from pathlib import Path

DATA_DIR = Path("world/map-data/data")
EXPORT_DIR = Path("world/map-data/exports")

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def export_nodes(nodes):
    features = []
    for node in nodes:
        pos = node['position']
        # GeoJSON uses [lon, lat] ordering, but we use x,y directly
        geometry = {
            "type": "Point",
            "coordinates": [pos['x'], pos['y']]
        }
        properties = {
            "id": node['id'],
            "name": node['name'],
            "type": node['type'],
            "continent_id": node.get('continent_id'),
            "region_id": node.get('region_id'),
            "transport_roles": node.get('transport_roles', []),
            "facilities": node.get('facilities', []),
            "description": node.get('description', ''),
            "tags": node.get('tags', []),
            "confidence": node.get('confidence', 'unknown')
        }
        features.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": properties
        })
    return {
        "type": "FeatureCollection",
        "features": features
    }

def export_routes(routes, nodes_map):
    features = []
    for route in routes:
        from_node = nodes_map.get(route['from'])
        to_node = nodes_map.get(route['to'])
        if not from_node or not to_node:
            continue  # skip if nodes not found

        from_pos = from_node['position']
        to_pos = to_node['position']
        geometry = {
            "type": "LineString",
            "coordinates": [
                [from_pos['x'], from_pos['y']],
                [to_pos['x'], to_pos['y']]
            ]
        }
        properties = {
            "id": route['id'],
            "name": route['name'],
            "type": route['type'],
            "mode": route['mode'],
            "from": route['from'],
            "to": route['to'],
            "distance_km": route.get('distance_km'),
            "estimated_time_hours": route.get('estimated_time_hours'),
            "cost_gold": route.get('cost_gold'),
            "danger_level": route.get('danger_level'),
            "status": route.get('status'),
            "seasonal": route.get('seasonal', False),
            "operators": route.get('operators', []),
            "tags": route.get('tags', []),
            "description": route.get('description', ''),
            "confidence": route.get('confidence', 'unknown')
        }
        features.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": properties
        })
    return {
        "type": "FeatureCollection",
        "features": features
    }

def export_hazards(hazards):
    features = []
    for hazard in hazards:
        center = hazard['center']
        radius = hazard.get('radius', 100)
        # Create a circular polygon approximation (20 sides)
        coords = []
        for i in range(21):  # 0 to 20 inclusive (21 points, closed)
            angle = (i / 20) * 2 * 3.14159
            x = center['x'] + radius * (180 / 3.14159)  # approximate degree scaling
            y = center['y'] + radius * (180 / 3.14159)
            # Simplified: use small square for now (exact circle requires more complex math)
            # For simplicity, just use center point with radius info in properties
            break
        # Simpler: just use center point, radius in properties
        geometry = {
            "type": "Point",
            "coordinates": [center['x'], center['y']]
        }
        properties = {
            "id": hazard['id'],
            "name": hazard['name'],
            "type": hazard['type'],
            "continent_id": hazard.get('continent_id'),
            "radius": radius,
            "severity": hazard.get('severity'),
            "seasonal": hazard.get('seasonal', False),
            "active_months": hazard.get('active_months', []),
            "effects": hazard.get('effects', {}),
            "description": hazard.get('description', ''),
            "confidence": hazard.get('confidence', 'unknown')
        }
        features.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": properties
        })
    return {
        "type": "FeatureCollection",
        "features": features
    }

def main():
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    # Load data
    nodes = load_json(DATA_DIR / "nodes.json")
    routes = load_json(DATA_DIR / "routes.json")
    hazards = load_json(DATA_DIR / "hazards.json")

    # Build node lookup
    nodes_map = {n['id']: n for n in nodes}

    # Export
    nodes_geojson = export_nodes(nodes)
    routes_geojson = export_routes(routes, nodes_map)
    hazards_geojson = export_hazards(hazards)

    # Save files
    with open(EXPORT_DIR / "nodes.geojson", 'w', encoding='utf-8') as f:
        json.dump(nodes_geojson, f, ensure_ascii=False, indent=2)
    with open(EXPORT_DIR / "routes.geojson", 'w', encoding='utf-8') as f:
        json.dump(routes_geojson, f, ensure_ascii=False, indent=2)
    with open(EXPORT_DIR / "hazards.geojson", 'w', encoding='utf-8') as f:
        json.dump(hazards_geojson, f, ensure_ascii=False, indent=2)

    # Also create a combined file
    all_features = nodes_geojson['features'] + routes_geojson['features'] + hazards_geojson['features']
    combined = {
        "type": "FeatureCollection",
        "features": all_features
    }
    with open(EXPORT_DIR / "world_transport.geojson", 'w', encoding='utf-8') as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)

    print(f"Exported {len(nodes)} nodes to nodes.geojson")
    print(f"Exported {len(routes)} routes to routes.geojson")
    print(f"Exported {len(hazards)} hazards to hazards.geojson")
    print(f"Combined export saved to world_transport.geojson")

if __name__ == "__main__":
    main()

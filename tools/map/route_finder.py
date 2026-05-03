#!/usr/bin/env python3
"""
Route Finder for Eternal Arcadia Map Data

Finds optimal routes between nodes using Dijkstra's algorithm.
Supports weighting by time, distance, safety (inverse of danger), and cost.
"""

import json
import argparse
import sys
from pathlib import Path
from heapq import heappush, heappop

DATA_DIR = Path("world/map-data/data")

# Route type allowances
ALLOWED_TYPES_DEFAULT = {"road", "rail", "sea", "air", "caravan", "submarine", "tunnel"}

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def build_graph(routes, weight="time", avoid_danger_level=None, allow_restricted=False,
                allow_air=True, allow_sea=True, month=None):
    """
    Build adjacency list from routes, applying filters and computing edge weights.
    Returns: dict {node_id: [(neighbor_id, weight, route_info), ...]}
    """
    graph = {}
    node_types = {}  # not used currently but available

    for route in routes:
        # Filter by status
        status = route.get("status", "active")
        if status == "forbidden" and not allow_restricted:
            continue
        if status == "restricted" and not allow_restricted:
            continue
        if status in {"closed", "dangerous"}:
            continue

        # Seasonal filter
        if route.get("seasonal") and month is not None:
            active_months = route.get("active_months", [])
            if month not in active_months:
                continue

        # Type filters
        rtype = route.get("type")
        if rtype == "air" and not allow_air:
            continue
        if rtype == "sea" and not allow_sea:
            continue

        # Danger level filter
        danger = route.get("danger_level", 0)
        if avoid_danger_level is not None and danger >= avoid_danger_level:
            continue

        from_node = route["from"]
        to_node = route["to"]

        # Compute weight based on chosen metric
        if weight == "time":
            w = route.get("estimated_time_hours", 1)
        elif weight == "distance":
            w = route.get("distance_km", 1)
        elif weight == "safety":
            # Higher danger => higher penalty
            danger_penalty = (danger + 1) ** 2  # quadratic penalty
            w = danger_penalty * route.get("estimated_time_hours", 1)
        elif weight == "cost":
            w = route.get("cost_gold", 1)
        else:
            w = route.get("estimated_time_hours", 1)

        # Ensure positive weight
        if w <= 0:
            w = 0.1

        # Bidirectional edges
        for src, dst in [(from_node, to_node), (to_node, from_node)]:
            if src not in graph:
                graph[src] = []
            graph[src].append((dst, w, route))

    return graph

def dijkstra(graph, start, goal):
    """
    Standard Dijkstra implementation.
    Returns: (distance, path list of (node, route))
    """
    INF = float('inf')
    dist = {node: INF for node in graph}
    prev = {}  # node -> (prev_node, route)
    dist[start] = 0
    heap = [(0, start)]

    while heap:
        d, u = heappop(heap)
        if d > dist[u]:
            continue
        if u == goal:
            break
        for v, w, route in graph.get(u, []):
            nd = d + w
            if nd < dist.get(v, INF):
                dist[v] = nd
                prev[v] = (u, route)
                heappush(heap, (nd, v))

    if goal not in prev and goal != start:
        return None, None

    # Reconstruct path
    path_nodes = []
    path_routes = []
    cur = goal
    while cur != start:
        path_nodes.append(cur)
        prev_node, route = prev.get(cur, (None, None))
        path_routes.append(route)
        cur = prev_node
        if cur is None:
            return None, None
    path_nodes.append(start)
    path_nodes.reverse()
    path_routes.reverse()
    return dist[goal], list(zip(path_nodes, path_routes + [None]))

def load_node_names(nodes):
    return {n['id']: n['name'] for n in nodes}

def format_time(hours):
    days = int(hours // 24)
    h = int(hours % 24)
    if days > 0:
        return f"{days}日{h}時間"
    return f"{h}時間"

def main():
    parser = argparse.ArgumentParser(description="Find optimal routes in Eternal Arcadia")
    parser.add_argument("--from", dest="src", required=True, help="Source node ID")
    parser.add_argument("--to", dest="dst", required=True, help="Destination node ID")
    parser.add_argument("--weight", choices=["time", "distance", "safety", "cost"],
                        default="time", help="Optimization metric")
    parser.add_argument("--avoid-danger-level", type=int, help="Avoid routes with danger >= this level")
    parser.add_argument("--allow-air", action="store_true", default=True, help="Allow air routes (default: enabled)")
    parser.add_argument("--allow-sea", action="store_true", default=True, help="Allow sea routes (default: enabled)")
    parser.add_argument("--allow-restricted", action="store_true", help="Allow restricted/seasonal routes")
    parser.add_argument("--month", type=int, help="Travel month (1-12) for seasonal routing")
    args = parser.parse_args()

    # Load data
    nodes = load_json(DATA_DIR / "nodes.json")
    routes = load_json(DATA_DIR / "routes.json")
    node_names = load_node_names(nodes)

    node_ids = {n['id'] for n in nodes}
    if args.src not in node_ids:
        print(f"Error: source node '{args.src}' not found", file=sys.stderr)
        sys.exit(1)
    if args.dst not in node_ids:
        print(f"Error: destination node '{args.dst}' not found", file=sys.stderr)
        sys.exit(1)

    # Build graph
    graph = build_graph(
        routes,
        weight=args.weight,
        avoid_danger_level=args.avoid_danger_level,
        allow_restricted=args.allow_restricted,
        allow_air=args.allow_air,
        allow_sea=args.allow_sea,
        month=args.month
    )

    if args.src not in graph:
        print(f"Error: no accessible routes from '{args.src}' with current filters", file=sys.stderr)
        sys.exit(1)

    # Find path
    total_weight, path_info = dijkstra(graph, args.src, args.dst)
    if path_info is None:
        print(f"No route found from {args.src} to {args.dst} with current filters.")
        sys.exit(1)

    # Format output
    src_name = node_names.get(args.src, args.src)
    dst_name = node_names.get(args.dst, args.dst)
    print(f"Route: {src_name} → {dst_name}")
    print(f"Total {args.weight}: ", end="")

    if args.weight == "time":
        print(f"{format_time(total_weight)}")
    elif args.weight == "distance":
        print(f"{total_weight:.0f} km")
    elif args.weight == "safety":
        print(f"{total_weight:.1f} (safety score, lower is better)")
    elif args.weight == "cost":
        print(f"{total_weight:.0f} gold")

    # Danger summary
    danger_levels = []
    print("\nSegments:")
    idx = 1
    for node, route in path_info:
        if route is None:
            break
        rname = route.get("name", "Unknown")
        rtype = route.get("type", "?")
        rmode = route.get("mode", "?")
        danger = route.get("danger_level", 0)
        danger_levels.append(danger)
        from_node_name = node_names.get(route['from'], route['from'])
        to_node_name = node_names.get(route['to'], route['to'])
        time_h = route.get("estimated_time_hours", 0)
        print(f"  {idx}. {rname} ({rtype}/{rmode})")
        print(f"     {from_node_name} → {to_node_name}")
        print(f"     時間: {format_time(time_h)}, 距離: {route.get('distance_km', 0)}km, 危険度: {danger}")
        idx += 1

    # Overall danger summary
    if danger_levels:
        max_d = max(danger_levels)
        avg_d = sum(danger_levels) / len(danger_levels)
        print(f"\n危険度概要: 最高={max_d}, 平均={avg_d:.1f}")

if __name__ == "__main__":
    main()

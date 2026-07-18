#!/usr/bin/env python3
"""
Route Finder for Eternal Arcadia Map Data

Finds optimal routes between nodes using Dijkstra's algorithm.
Supports weighting by time, distance, safety (inverse of danger), and cost.
"""

import argparse
import sys
from heapq import heappush, heappop

try:
    from tools.map.common import DATA_DIR, load_json
except ImportError:  # run as a script from tools/map
    from common import DATA_DIR, load_json

def build_graph(routes, weight="time", avoid_danger_level=None, allow_restricted=False,
                allow_air=True, allow_sea=True, month=None):
    """
    Build adjacency list from routes, applying filters and computing edge weights.
    Returns: dict {node_id: [(neighbor_id, weight, route_info), ...]}
    """
    graph = {}

    for route in routes:
        # Filter by status
        status = route.get("status", "active")
        if status == "forbidden":
            continue
        if status == "restricted" and not allow_restricted:
            continue
        if status in {"closed", "dangerous"}:
            continue

        # Seasonal filter: routes with seasonal=true OR active_months field are considered seasonal
        is_seasonal = route.get("seasonal", False) or "active_months" in route
        if is_seasonal and month is not None:
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
    parser.add_argument("--avoid-danger-level", type=int, help="Avoid routes with danger >= this level (e.g., 4 = avoid very dangerous)")
    # Deprecated: use --no-air instead
    parser.add_argument("--allow-air", action="store_true", help="(DEPRECATED) Include air routes (default: included without this flag). Use --no-air to exclude.")
    # Deprecated: use --no-sea instead
    parser.add_argument("--allow-sea", action="store_true", help="(DEPRECATED) Include sea routes (default: included without this flag). Use --no-sea to exclude.")
    parser.add_argument("--no-air", action="store_true", help="Exclude air routes")
    parser.add_argument("--no-sea", action="store_true", help="Exclude sea routes")
    parser.add_argument("--allow-restricted", action="store_true", help="Include routes with status 'restricted' (does not affect seasonal routes)")
    parser.add_argument("--month", type=int, choices=range(1,13), help="Travel month (1-12) for seasonal route filtering")
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

    # Resolve air/sea allowances with backward compatibility
    # Default: air and sea are allowed.
    # --no-air / --no-sea explicitly exclude.
    # --allow-air / --allow-sea explicitly include (deprecated, for compatibility).
    # If both --no-? and --allow-? are given, --no-? takes precedence.
    allow_air = not args.no_air
    if args.allow_air and not args.no_air:
        allow_air = True
    allow_sea = not args.no_sea
    if args.allow_sea and not args.no_sea:
        allow_sea = True

    # Build graph
    graph = build_graph(
        routes,
        weight=args.weight,
        avoid_danger_level=args.avoid_danger_level,
        allow_restricted=args.allow_restricted,
        allow_air=allow_air,
        allow_sea=allow_sea,
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
        
        # Build extra info line: status and seasonal info
        extra_parts = []
        status = route.get("status", "active")
        seasonal = route.get("seasonal", False)
        active_months = route.get("active_months", [])
        extra_parts.append(f"status: {status}")
        if seasonal or active_months:
            months_str = ",".join(str(m) for m in active_months) if active_months else "none"
            note = ""
            if args.month is None:
                note = " (month not specified; availability uncertain)"
            extra_parts.append(f"seasonal: {seasonal}, active_months: {months_str}{note}")
        
        print(f"  {idx}. {rname} ({rtype}/{rmode})")
        print(f"     {from_node_name} → {to_node_name}")
        if extra_parts:
            print(f"     [{'; '.join(extra_parts)}]")
        print(f"     時間: {format_time(time_h)}, 距離: {route.get('distance_km', 0)}km, 危険度: {danger}")
        idx += 1

    # Overall danger summary
    if danger_levels:
        max_d = max(danger_levels)
        avg_d = sum(danger_levels) / len(danger_levels)
        print(f"\n危険度概要: 最高={max_d}, 平均={avg_d:.1f}")

if __name__ == "__main__":
    main()

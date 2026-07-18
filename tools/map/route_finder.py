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


BLOCKED_ROUTE_STATUSES = {"forbidden", "experimental", "dangerous", "closed"}
DEFAULT_ROUTE_COST = 9999
MINIMUM_EDGE_COST = 0.1


def _metric_value(route, priority_keys):
    """Return the first finite numeric metric used by the browser planner too."""
    for key in priority_keys:
        value = route.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    return DEFAULT_ROUTE_COST


def compute_route_cost(route, weight="time"):
    """Compute an edge cost using the cross-client route-planning contract."""
    if weight == "distance":
        return _metric_value(route, ("distance_km", "estimated_time_hours"))
    if weight == "safety":
        base_cost = _metric_value(route, ("estimated_time_hours", "distance_km"))
        danger = max(0, route.get("danger_level", 0))
        return base_cost * (danger + 1) ** 2
    if weight == "cost":
        return _metric_value(route, ("cost_gold", "estimated_time_hours", "distance_km"))
    return _metric_value(route, ("estimated_time_hours", "distance_km"))


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
        if status in BLOCKED_ROUTE_STATUSES:
            continue
        if status == "restricted" and not allow_restricted:
            continue

        # A seasonal status, flag, or active_months declaration all opt into
        # seasonal availability. With a requested month, fail closed unless it
        # is explicitly listed. Without a month, retain the route but report
        # the unresolved availability in the formatted result.
        is_seasonal = (
            status == "seasonal"
            or route.get("seasonal", False)
            or "active_months" in route
        )
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

        # Dijkstra requires non-negative edge weights. Use the same lower bound
        # as the browser planner so sub-hour/sub-gold routes produce identical
        # paths in both clients.
        w = max(MINIMUM_EDGE_COST, compute_route_cost(route, weight))

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


def oriented_route_nodes(current_node, route):
    """Return a bidirectional route in the direction it is being traversed."""
    if route.get("from") == current_node:
        return current_node, route.get("to")
    if route.get("to") == current_node:
        return current_node, route.get("from")
    raise ValueError(f"Route {route.get('id', '<unknown>')} is not connected to {current_node}")


def format_time(hours):
    total_minutes = round(hours * 60)
    days, remaining_minutes = divmod(total_minutes, 24 * 60)
    whole_hours, minutes = divmod(remaining_minutes, 60)
    parts = []
    if days:
        parts.append(f"{days}日")
    if whole_hours or (not days and not minutes):
        parts.append(f"{whole_hours}時間")
    if minutes:
        parts.append(f"{minutes}分")
    return "".join(parts)


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
    if args.src == args.dst:
        print("Error: source and destination must be different", file=sys.stderr)
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
        # Routes are bidirectional. Use the reconstructed path node rather than
        # the route's declaration order so a reverse traversal is not printed
        # in the wrong direction.
        current_node, next_node = oriented_route_nodes(node, route)
        from_node_name = node_names.get(current_node, current_node)
        to_node_name = node_names.get(next_node, next_node)
        time_h = route.get("estimated_time_hours", 0)
        
        # Build extra info line: status and seasonal info
        extra_parts = []
        status = route.get("status", "active")
        seasonal = route.get("seasonal", False)
        active_months = route.get("active_months", [])
        extra_parts.append(f"status: {status}")
        if status == "seasonal" or seasonal or active_months:
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

#!/usr/bin/env python3
"""
Static Network Renderer

Renders a simple static visualization of the map network (nodes and routes).
Uses only Python standard library; outputs SVG.
"""

try:
    from tools.map.common import DATA_DIR, EXPORT_DIR, load_json
except ImportError:  # run as a script from tools/map
    from common import DATA_DIR, EXPORT_DIR, load_json

# SVG dimensions
WIDTH = 1200
HEIGHT = 1000
MARGIN = 50

# Coordinate scaling: internal (0-10000) -> SVG
def scale_coord(x, y):
    """Map internal coordinates to SVG viewBox with margins."""
    avail_w = WIDTH - 2 * MARGIN
    avail_h = HEIGHT - 2 * MARGIN
    # Flip y for SVG (origin top-left)
    svg_x = MARGIN + (x / 10000) * avail_w
    svg_y = MARGIN + ((10000 - y) / 10000) * avail_h
    return svg_x, svg_y

def main():
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    nodes = load_json(DATA_DIR / "nodes.json")
    routes = load_json(DATA_DIR / "routes.json")

    nodes_map = {n['id']: n for n in nodes}

    # Start building SVG
    svg_lines = []
    svg_lines.append(f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" xmlns="http://www.w3.org/2000/svg">')
    svg_lines.append('<style>')
    svg_lines.append('  .route { fill: none; stroke-width: 2; opacity: 0.7; }')
    svg_lines.append('  .node { fill: #4a90d9; stroke: #2c5aa0; stroke-width: 2; }')
    svg_lines.append('  .node-label { font-family: sans-serif; font-size: 10px; fill: #333; }')
    svg_lines.append('  .route-road { stroke: #8b4513; }')
    svg_lines.append('  .route-sea { stroke: #1e90ff; }')
    svg_lines.append('  .route-air { stroke: #ff69b4; }')
    svg_lines.append('  .route-rail { stroke: #2e8b57; }')
    svg_lines.append('  .route-caravan { stroke: #daa520; }')
    svg_lines.append('  .route-special { stroke: #9932cc; }')
    svg_lines.append('</style>')

    # Draw routes first (so nodes appear on top)
    for route in routes:
        from_id = route['from']
        to_id = route['to']
        from_node = nodes_map.get(from_id)
        to_node = nodes_map.get(to_id)
        if not from_node or not to_node:
            continue

        x1, y1 = scale_coord(from_node['position']['x'], from_node['position']['y'])
        x2, y2 = scale_coord(to_node['position']['x'], to_node['position']['y'])

        rtype = route.get('type', 'road')
        css_class = f"route route-{rtype}"
        # Tooltip via title
        label = route.get('name', route['id'])
        svg_lines.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" class="{css_class}">'
            f'<title>{label} ({rtype})</title></line>'
        )

    # Draw nodes
    for node in nodes:
        x, y = scale_coord(node['position']['x'], node['position']['y'])
        # Node size based on type
        size = 8
        if node['type'] == 'capital':
            size = 12
        elif node['type'] in ['port', 'airport', 'city']:
            size = 10

        # Color based on node type
        fill = "#4a90d9"
        if node['type'] == 'capital':
            fill = "#ff4444"
        elif node['type'] == 'port':
            fill = "#1e90ff"
        elif node['type'] in ['airport', 'air_terminal']:
            fill = "#ff69b4"
        elif node['type'] == 'floating_island':
            fill = "#9370db"

        svg_lines.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{size}" fill="{fill}" stroke="#2c5aa0" stroke-width="2" class="node">'
            f'<title>{node["name"]} ({node["type"]})</title></circle>'
        )

        # Label for major nodes
        if node['type'] in ['capital', 'port', 'airport', 'city', 'floating_island']:
            svg_lines.append(
                f'<text x="{x+12:.1f}" y="{y-5:.1f}" class="node-label">{node["name"]}</text>'
            )

    # Close SVG
    svg_lines.append('</svg>')

    # Write file
    output_path = EXPORT_DIR / "world_transport_network.svg"
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(svg_lines))

    print(f"Rendered {len(nodes)} nodes and {len(routes)} routes to {output_path}")
    print("(SVG format - open in browser or vector viewer)")

if __name__ == "__main__":
    main()

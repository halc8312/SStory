import json
import unittest
from pathlib import Path

from tools.map import route_finder
from tools.map import validate_map_data


class RouteFinderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture_path = Path(__file__).parent / "fixtures" / "route-planner-cases.json"
        cls.shared_fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    def test_build_graph_applies_filters_and_weight_rules(self):
        routes = [
            {
                "id": "safe-road",
                "from": "a",
                "to": "b",
                "type": "road",
                "mode": "walking",
                "status": "active",
                "danger_level": 1,
                "estimated_time_hours": 4,
            },
            {
                "id": "risky-air",
                "from": "b",
                "to": "c",
                "type": "air",
                "mode": "airship",
                "status": "restricted",
                "danger_level": 3,
                "estimated_time_hours": 2,
            },
            {
                "id": "seasonal-sea",
                "from": "a",
                "to": "c",
                "type": "sea",
                "mode": "sailing_ship",
                "status": "active",
                "seasonal": True,
                "active_months": [6, 7],
                "danger_level": 0,
                "estimated_time_hours": 8,
            },
            {
                "id": "closed-road",
                "from": "c",
                "to": "d",
                "type": "road",
                "mode": "walking",
                "status": "closed",
                "danger_level": 0,
                "estimated_time_hours": 1,
            },
            {
                "id": "free-route",
                "from": "b",
                "to": "d",
                "type": "road",
                "mode": "walking",
                "status": "active",
                "danger_level": 0,
                "cost_gold": 0,
            },
        ]

        filtered = route_finder.build_graph(
            routes,
            weight="time",
            avoid_danger_level=3,
            allow_restricted=False,
            allow_air=False,
            allow_sea=True,
            month=1,
        )
        self.assertEqual(set(filtered.keys()), {"a", "b", "d"})
        self.assertEqual(filtered["a"][0][0], "b")
        self.assertEqual(filtered["a"][0][1], 4)
        self.assertEqual(filtered["b"][-1][0], "d")
        self.assertNotIn("c", filtered)

        cost_graph = route_finder.build_graph(
            routes,
            weight="cost",
            allow_restricted=True,
            allow_air=True,
            allow_sea=True,
        )
        self.assertEqual(cost_graph["b"][-1][1], 0.1)

        safety_graph = route_finder.build_graph(
            routes,
            weight="safety",
            allow_restricted=True,
            allow_air=True,
            allow_sea=True,
        )
        safety_weight = next(weight for node, weight, route in safety_graph["b"] if route["id"] == "risky-air")
        self.assertEqual(safety_weight, 32)

    def test_dijkstra_returns_shortest_path_and_handles_unreachable_nodes(self):
        graph = {
            "a": [("b", 2, {"id": "ab"}), ("c", 5, {"id": "ac"})],
            "b": [("c", 1, {"id": "bc"})],
            "c": [],
        }

        total, path_info = route_finder.dijkstra(graph, "a", "c")

        self.assertEqual(total, 3)
        self.assertEqual([node for node, _ in path_info], ["a", "b", "c"])
        self.assertEqual(path_info[0][1]["id"], "ab")
        self.assertEqual(path_info[1][1]["id"], "bc")
        self.assertIsNone(path_info[2][1])

        unreachable_total, unreachable_path = route_finder.dijkstra(graph, "c", "a")
        self.assertIsNone(unreachable_total)
        self.assertIsNone(unreachable_path)

    def test_format_time_handles_hours_and_days(self):
        self.assertEqual(route_finder.format_time(5), "5時間")
        self.assertEqual(route_finder.format_time(27), "1日3時間")
        self.assertEqual(route_finder.format_time(0.5), "30分")

    def test_oriented_route_nodes_handles_reverse_traversal(self):
        route = {"id": "ab", "from": "a", "to": "b"}
        self.assertEqual(route_finder.oriented_route_nodes("a", route), ("a", "b"))
        self.assertEqual(route_finder.oriented_route_nodes("b", route), ("b", "a"))
        with self.assertRaises(ValueError):
            route_finder.oriented_route_nodes("c", route)

    def test_shared_route_contract_blocks_statuses_and_applies_seasons(self):
        routes = self.shared_fixture["routes"]
        summer = route_finder.build_graph(routes, month=7)
        winter = route_finder.build_graph(routes, month=1)
        unrestricted = route_finder.build_graph(routes, month=7, allow_restricted=True)

        summer_ids = {route["id"] for edges in summer.values() for _, _, route in edges}
        winter_ids = {route["id"] for edges in winter.values() for _, _, route in edges}
        unrestricted_ids = {route["id"] for edges in unrestricted.values() for _, _, route in edges}
        self.assertIn("seasonal_bc", summer_ids)
        self.assertNotIn("seasonal_bc", winter_ids)
        self.assertIn("restricted_bd", unrestricted_ids)
        for blocked_id in ("forbidden_ac", "experimental_ad", "dangerous_ae", "closed_ce"):
            self.assertNotIn(blocked_id, unrestricted_ids)

    def test_shared_route_contract_uses_identical_weights(self):
        active = next(route for route in self.shared_fixture["routes"] if route["id"] == "active_ab")
        self.assertEqual(route_finder.compute_route_cost(active, "time"), 4)
        self.assertEqual(route_finder.compute_route_cost(active, "distance"), 40)
        self.assertEqual(route_finder.compute_route_cost(active, "safety"), 16)
        self.assertEqual(route_finder.compute_route_cost(active, "cost"), 10)

        subminimum = {
            "from": "a",
            "to": "b",
            "estimated_time_hours": 0.05,
            "distance_km": 0.05,
            "cost_gold": 0.05,
            "danger_level": 0,
        }
        for weight in ("time", "distance", "safety", "cost"):
            graph = route_finder.build_graph([subminimum], weight=weight)
            self.assertEqual(graph["a"][0][1], route_finder.MINIMUM_EDGE_COST)


class ValidateMapDataTests(unittest.TestCase):
    def test_validate_json_schema_rejects_invalid_collection_entries(self):
        errors = validate_map_data.validate_json_schema(
            [{"id": "Not_Snake_Case"}],
            "node.schema.json",
            collection=True,
        )

        self.assertTrue(any("schema violation at 0.id" in error for error in errors))
        self.assertTrue(any("'name' is a required property" in error for error in errors))

    def test_collect_ids_ignores_malformed_records(self):
        self.assertEqual(
            validate_map_data.collect_ids(
                [{"id": "valid"}, {"id": 3}, {"name": "missing"}, "bad"]
            ),
            {"valid"},
        )
        self.assertEqual(validate_map_data.data_count(None), 0)
        self.assertEqual(validate_map_data.data_count([1, 2]), 2)

    def test_validate_continents_reports_structural_errors(self):
        continents = [
            {"id": "c1", "type": "continent", "center": {"x": 10, "y": 20}, "confidence": "canon"},
            {"id": "c1", "type": "island", "center": {"x": 20000, "y": -1}, "confidence": "wrong"},
            {"id": "c2", "type": "continent", "confidence": "canon"},
        ]

        errors = validate_map_data.validate_continents(continents, set())

        self.assertIn("Duplicate continent IDs found", errors)
        self.assertIn("Continent c1: type must be 'continent'", errors)
        self.assertIn("Continent c1: center coordinates out of range", errors)
        self.assertIn("Continent c1: invalid confidence level", errors)
        self.assertIn("Continent c2: missing center", errors)

    def test_validate_routes_and_hazards_report_invalid_references_and_ranges(self):
        route_errors = validate_map_data.validate_routes(
            [
                {
                    "id": "r1",
                    "from": "missing",
                    "to": "n2",
                    "type": "portal",
                    "mode": "teleport",
                    "status": "broken",
                    "danger_level": 9,
                    "confidence": "unknown",
                },
                {
                    "id": "r1",
                    "from": "n1",
                    "to": "missing",
                    "type": "road",
                    "mode": "walking",
                    "status": "active",
                    "danger_level": 2,
                    "confidence": "canon",
                },
            ],
            set(),
            {"n1", "n2"},
        )
        hazard_errors = validate_map_data.validate_hazards(
            [
                {
                    "id": "h1",
                    "continent_id": "missing",
                    "type": "lava",
                    "severity": 8,
                    "confidence": "unknown",
                },
                {
                    "id": "h1",
                    "continent_id": "c1",
                    "type": "fog",
                    "severity": 1,
                    "confidence": "canon",
                },
            ],
            set(),
            {"c1"},
        )

        self.assertIn("Duplicate route IDs found", route_errors)
        self.assertIn("Route r1: invalid from node 'missing'", route_errors)
        self.assertIn("Route r1: invalid to node 'missing'", route_errors)
        self.assertIn("Route r1: invalid type 'portal'", route_errors)
        self.assertIn("Route r1: invalid mode 'teleport'", route_errors)
        self.assertIn("Route r1: invalid status 'broken'", route_errors)
        self.assertIn("Route r1: danger_level must be 0-5", route_errors)
        self.assertIn("Route r1: invalid confidence level", route_errors)

        self.assertIn("Duplicate hazard IDs found", hazard_errors)
        self.assertIn("Hazard h1: invalid continent_id 'missing'", hazard_errors)
        self.assertIn("Hazard h1: invalid type 'lava'", hazard_errors)
        self.assertIn("Hazard h1: severity must be 0-5", hazard_errors)
        self.assertIn("Hazard h1: invalid confidence level", hazard_errors)

    def test_validate_pixel_mapping_checks_coverage_bounds_and_shape(self):
        mapping = {
            "image_width": 100,
            "image_height": 50,
            "nodes": {"n1": {"x": 10, "y": 20}, "unknown": {"x": 0, "y": 0}},
            "continents": {"c1": {"x": 101, "y": 20}},
            "hazards": {"h1": {"x": "bad", "y": 20}},
            "hazard_radius_scale": 0,
        }

        errors = validate_map_data.validate_pixel_mapping(mapping, {"n1", "n2"}, {"c1"}, {"h1"})

        self.assertIn("nodes: missing canonical ID 'n2'", errors)
        self.assertIn("nodes: unknown ID 'unknown'", errors)
        self.assertIn("continents.c1: x outside image bounds", errors)
        self.assertIn("hazards.h1: x must be a number", errors)
        self.assertIn("hazard_radius_scale must be a positive number", errors)


if __name__ == "__main__":
    unittest.main()

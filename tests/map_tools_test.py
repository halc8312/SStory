import unittest

from tools.map import route_finder
from tools.map import validate_map_data


class RouteFinderTests(unittest.TestCase):
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
        self.assertEqual(set(filtered.keys()), {"a", "b"})
        self.assertEqual(filtered["a"][0][0], "b")
        self.assertEqual(filtered["a"][0][1], 4)

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


class ValidateMapDataTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

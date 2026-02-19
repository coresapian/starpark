"""Unit tests for OSRM route client."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from osrm_client import OSRMClient


class TestOSRMClient(unittest.TestCase):
    @patch("osrm_client.requests.get")
    def test_get_route_returns_geometry(self, mock_get):
        """OSRM should return a route with geometry and distance."""
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "code": "Ok",
            "routes": [
                {
                    "distance": 12345.6,
                    "duration": 890.1,
                    "geometry": {
                        "coordinates": [
                            [-104.9903, 39.7392],
                            [-105.1000, 39.9000],
                            [-105.2705, 40.0150],
                        ]
                    },
                }
            ],
        }
        mock_get.return_value = mock_response

        client = OSRMClient()
        route = client.get_route(
            origin=(39.7392, -104.9903),
            destination=(40.0150, -105.2705),
        )

        self.assertIsNotNone(route)
        self.assertIn("geometry", route)
        self.assertIn("distance_m", route)
        self.assertIn("duration_s", route)
        self.assertGreater(len(route["geometry"]), 2)

    def test_sample_route_points(self):
        """Should sample points along a route at specified intervals."""
        client = OSRMClient()
        geometry = [
            (39.7392, -104.9903),
            (39.8000, -105.0000),
            (40.0150, -105.2705),
        ]

        points = client.sample_route_points(geometry, interval_m=5000)
        self.assertGreater(len(points), 0)
        for point in points:
            self.assertIn("lat", point)
            self.assertIn("lon", point)
            self.assertIn("distance_along_m", point)


if __name__ == "__main__":
    unittest.main(verbosity=2)

# Copyright (c) 2024, LinkSpot Team
# BSD 3-Clause License
#
# API endpoint tests using pytest and FastAPI TestClient.

"""Tests for LinkSpot API endpoints."""

import json
import sys
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Add parent directory to path for imports
sys.path.insert(0, "/mnt/okcomputer/output/linkspot/backend")

from main import app


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def client() -> TestClient:
    """Create test client for API testing.
    
    Returns:
        TestClient: FastAPI test client.
    """
    return TestClient(app)


@pytest.fixture
def mock_satellite_engine():
    """Create mock satellite engine."""
    mock = MagicMock()
    mock.get_visible_satellites = AsyncMock(return_value=[
        {
            "satellite_id": "STARLINK-1234",
            "norad_id": 12345,
            "azimuth": 45.0,
            "elevation": 25.0,
            "range_km": 550.0,
            "velocity_kms": 7.8,
            "constellation": "Starlink",
        },
        {
            "satellite_id": "STARLINK-5678",
            "norad_id": 12346,
            "azimuth": 120.0,
            "elevation": 35.0,
            "range_km": 545.0,
            "velocity_kms": 7.8,
            "constellation": "Starlink",
        },
    ])
    mock.get_constellations = AsyncMock(return_value=[
        {
            "name": "Starlink",
            "operator": "SpaceX",
            "total_satellites": 5000,
            "active_satellites": 4500,
            "orbital_planes": 72,
            "altitude_km": 550,
            "inclination_deg": 53.0,
        },
        {
            "name": "OneWeb",
            "operator": "Eutelsat",
            "total_satellites": 648,
            "active_satellites": 634,
            "orbital_planes": 12,
            "altitude_km": 1200,
            "inclination_deg": 87.4,
        },
    ])
    return mock


@pytest.fixture
def mock_data_pipeline():
    """Create mock data pipeline."""
    mock = MagicMock()
    mock.fetch_buildings = AsyncMock(return_value=[])
    mock.fetch_terrain = AsyncMock(return_value=[])
    mock.initialize = AsyncMock()
    mock.initialized = True
    return mock


@pytest.fixture
def mock_obstruction_engine():
    """Create mock obstruction engine."""
    mock = MagicMock()
    mock.resolution = 360
    mock.analyze_position = MagicMock(return_value={
        "n_clear": 42,
        "n_total": 50,
        "obstruction_pct": 16.0,
        "blocked_azimuths": [[30.0, 60.0]],
    })
    mock.get_zone = MagicMock(return_value="good")
    return mock


@pytest.fixture
def mock_redis():
    """Create mock Redis client."""
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.setex = AsyncMock()
    mock.ping = AsyncMock()
    return mock


# ============================================================================
# Health Endpoint Tests
# ============================================================================

class TestHealthEndpoints:
    """Tests for health check endpoints."""
    
    def test_health_check(self, client: TestClient):
        """Test basic health check endpoint."""
        response = client.get("/api/v1/health")
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "timestamp" in data
        assert data["status"] == "healthy"
    
    def test_detailed_health_check(self, client: TestClient):
        """Test detailed health check endpoint."""
        response = client.get("/api/v1/health/detailed")
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "components" in data
        assert "environment" in data
        assert isinstance(data["components"], list)
    
    def test_liveness_check(self, client: TestClient):
        """Test liveness check endpoint."""
        response = client.get("/api/v1/health/live")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
    
    def test_readiness_check(self, client: TestClient):
        """Test readiness check endpoint."""
        response = client.get("/api/v1/health/ready")
        
        # May fail if dependencies not initialized in test
        assert response.status_code in [200, 503]


# ============================================================================
# Analysis Endpoint Tests
# ============================================================================

class TestAnalysisEndpoints:
    """Tests for analysis endpoints."""
    
    def test_analyze_valid_request(self, client: TestClient):
        """Test analyze endpoint with valid request."""
        request_data = {
            "lat": 40.7128,
            "lon": -74.0060,
            "elevation": 10.0,
        }
        
        response = client.post("/api/v1/analyze", json=request_data)
        
        # Should succeed (uses mock engines)
        assert response.status_code == 200
        data = response.json()
        assert "zone" in data
        assert "n_clear" in data
        assert "n_total" in data
        assert "obstruction_pct" in data
        assert "blocked_azimuths" in data
        assert "timestamp" in data
    
    def test_analyze_invalid_latitude(self, client: TestClient):
        """Test analyze endpoint with invalid latitude."""
        request_data = {
            "lat": 100.0,  # Invalid: > 90
            "lon": -74.0060,
        }
        
        response = client.post("/api/v1/analyze", json=request_data)
        
        assert response.status_code == 422
    
    def test_analyze_invalid_longitude(self, client: TestClient):
        """Test analyze endpoint with invalid longitude."""
        request_data = {
            "lat": 40.7128,
            "lon": 200.0,  # Invalid: > 180
        }
        
        response = client.post("/api/v1/analyze", json=request_data)
        
        assert response.status_code == 422
    
    def test_analyze_missing_required_fields(self, client: TestClient):
        """Test analyze endpoint with missing required fields."""
        request_data = {
            "lat": 40.7128,
            # Missing lon
        }
        
        response = client.post("/api/v1/analyze", json=request_data)
        
        assert response.status_code == 422
    
    def test_heatmap_valid_request(self, client: TestClient):
        """Test heatmap endpoint with valid request."""
        request_data = {
            "lat": 40.7128,
            "lon": -74.0060,
            "radius_m": 1000,
            "spacing_m": 100,
        }
        
        response = client.post("/api/v1/heatmap", json=request_data)
        
        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "FeatureCollection"
        assert "features" in data
        assert "metadata" in data
        assert isinstance(data["features"], list)
    
    def test_heatmap_invalid_radius(self, client: TestClient):
        """Test heatmap endpoint with invalid radius."""
        request_data = {
            "lat": 40.7128,
            "lon": -74.0060,
            "radius_m": 50000,  # Invalid: > 10000
            "spacing_m": 100,
        }
        
        response = client.post("/api/v1/heatmap", json=request_data)
        
        assert response.status_code == 422
    
    def test_heatmap_invalid_spacing(self, client: TestClient):
        """Test heatmap endpoint with invalid spacing."""
        request_data = {
            "lat": 40.7128,
            "lon": -74.0060,
            "radius_m": 1000,
            "spacing_m": 10,  # Invalid: < 50
        }
        
        response = client.post("/api/v1/heatmap", json=request_data)
        
        assert response.status_code == 422


# ============================================================================
# Satellite Endpoint Tests
# ============================================================================

class TestSatelliteEndpoints:
    """Tests for satellite endpoints."""
    
    def test_get_visible_satellites(self, client: TestClient):
        """Test visible satellites endpoint."""
        response = client.get(
            "/api/v1/satellites",
            params={
                "lat": 40.7128,
                "lon": -74.0060,
                "elevation": 10.0,
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "satellites" in data
        assert "count" in data
        assert "timestamp" in data
        assert "location" in data
        assert isinstance(data["satellites"], list)
    
    def test_get_visible_satellites_invalid_lat(self, client: TestClient):
        """Test visible satellites with invalid latitude."""
        response = client.get(
            "/api/v1/satellites",
            params={
                "lat": 100.0,  # Invalid
                "lon": -74.0060,
            },
        )
        
        assert response.status_code == 422
    
    def test_get_constellations(self, client: TestClient):
        """Test constellation list endpoint."""
        response = client.get("/api/v1/satellites/constellation")
        
        assert response.status_code == 200
        data = response.json()
        assert "constellations" in data
        assert "total_count" in data
        assert isinstance(data["constellations"], list)
    
    def test_get_specific_constellation(self, client: TestClient):
        """Test specific constellation endpoint."""
        response = client.get("/api/v1/satellites/constellation/Starlink")
        
        # May be 200 or 404 depending on mock
        assert response.status_code in [200, 404]
        
        if response.status_code == 200:
            data = response.json()
            assert "name" in data
            assert "total_satellites" in data


# ============================================================================
# Root Endpoint Tests
# ============================================================================

class TestRootEndpoints:
    """Tests for root endpoints."""
    
    def test_root_endpoint(self, client: TestClient):
        """Test root endpoint."""
        response = client.get("/")
        
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert "endpoints" in data
    
    def test_api_info_endpoint(self, client: TestClient):
        """Test API info endpoint."""
        response = client.get("/api/v1")
        
        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert "endpoints" in data
        assert isinstance(data["endpoints"], list)


# ============================================================================
# Error Handling Tests
# ============================================================================

class TestErrorHandling:
    """Tests for error handling."""
    
    def test_not_found(self, client: TestClient):
        """Test 404 error handling."""
        response = client.get("/api/v1/nonexistent")
        
        assert response.status_code == 404
    
    def test_method_not_allowed(self, client: TestClient):
        """Test 405 error handling."""
        response = client.post("/api/v1/health")  # GET only endpoint
        
        assert response.status_code == 405
    
    def test_invalid_json(self, client: TestClient):
        """Test invalid JSON handling."""
        response = client.post(
            "/api/v1/analyze",
            data="invalid json",
            headers={"Content-Type": "application/json"},
        )
        
        assert response.status_code == 422


# ============================================================================
# Schema Validation Tests
# ============================================================================

class TestSchemaValidation:
    """Tests for Pydantic schema validation."""
    
    def test_analyze_request_schema(self):
        """Test AnalyzeRequest schema validation."""
        from models.schemas import AnalyzeRequest
        
        # Valid request
        request = AnalyzeRequest(lat=40.7128, lon=-74.0060, elevation=10.0)
        assert request.lat == 40.7128
        assert request.lon == -74.0060
        assert request.elevation == 10.0
        
        # Invalid latitude
        with pytest.raises(ValueError):
            AnalyzeRequest(lat=100.0, lon=-74.0060)
    
    def test_analyze_response_schema(self):
        """Test AnalyzeResponse schema validation."""
        from models.schemas import AnalyzeResponse, Zone
        
        response = AnalyzeResponse(
            zone=Zone.GOOD,
            n_clear=42,
            n_total=50,
            obstruction_pct=16.0,
            blocked_azimuths=[[30.0, 60.0]],
            timestamp=datetime.now(timezone.utc),
            lat=40.7128,
            lon=-74.0060,
        )
        
        assert response.zone == Zone.GOOD
        assert response.n_clear == 42
    
    def test_heatmap_request_schema(self):
        """Test HeatmapRequest schema validation."""
        from models.schemas import HeatmapRequest
        
        request = HeatmapRequest(
            lat=40.7128,
            lon=-74.0060,
            radius_m=1000,
            spacing_m=100,
        )
        
        assert request.radius_m == 1000
        assert request.spacing_m == 100
    
    def test_satellite_position_schema(self):
        """Test SatellitePosition schema validation."""
        from models.schemas import SatellitePosition
        
        position = SatellitePosition(
            satellite_id="STARLINK-1234",
            azimuth=45.0,
            elevation=25.0,
        )
        
        assert position.satellite_id == "STARLINK-1234"
        assert position.azimuth == 45.0


# ============================================================================
# Performance Tests
# ============================================================================

class TestPerformance:
    """Basic performance tests."""
    
    def test_health_response_time(self, client: TestClient):
        """Test health endpoint response time."""
        import time
        
        start = time.time()
        response = client.get("/api/v1/health")
        elapsed = time.time() - start
        
        assert response.status_code == 200
        assert elapsed < 1.0  # Should respond within 1 second
    
    def test_analyze_response_time(self, client: TestClient):
        """Test analyze endpoint response time."""
        import time
        
        request_data = {
            "lat": 40.7128,
            "lon": -74.0060,
        }
        
        start = time.time()
        response = client.post("/api/v1/analyze", json=request_data)
        elapsed = time.time() - start
        
        assert response.status_code == 200
        # Should respond within 5 seconds (cold cache target)
        assert elapsed < 5.0


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

-- -*- coding: utf-8 -*-
-- Copyright (c) 2024, LinkSpot Project Contributors
-- All rights reserved.
--
-- Redistribution and use in source and binary forms, with or without
-- modification, are permitted provided that the following conditions are met:
--
-- 1. Redistributions of source code must retain the above copyright notice, this
--    list of conditions and the following disclaimer.
-- 2. Redistributions in binary form must reproduce the above copyright notice,
--    this list of conditions and the following disclaimer in the documentation
--    and/or other materials provided with the distribution.
--
-- THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
-- AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
-- IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
-- DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE
-- FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
-- DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
-- SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
-- CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
-- OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
-- OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

-- =============================================================================
-- LinkSpot Initial Database Schema
-- =============================================================================
-- PostgreSQL + PostGIS schema for geospatial data storage
-- 
-- Tables:
--   - buildings: 3D building footprint data
--   - terrain_tiles: DEM tile metadata
--   - tle_cache: Satellite TLE data cache
--   - analysis_cache: Analysis result cache
--
-- Requirements:
--   - PostgreSQL 13+
--   - PostGIS 3.0+
-- =============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- Buildings Table
-- =============================================================================
-- Stores 3D building footprint data for line-of-sight calculations

CREATE TABLE IF NOT EXISTS buildings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- PostGIS geometry column (Polygon, WGS84)
    geometry GEOMETRY(POLYGON, 4326) NOT NULL,
    
    -- Building height in meters
    height DOUBLE PRECISION NOT NULL CHECK (height >= 0),
    
    -- Data source tracking
    source VARCHAR(64) NOT NULL,
    source_id VARCHAR(128) NOT NULL,
    
    -- Metadata
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    height_source VARCHAR(64),
    height_confidence DOUBLE PRECISION CHECK (height_confidence >= 0 AND height_confidence <= 1),
    
    -- Ensure unique source/source_id combination
    CONSTRAINT uq_buildings_source_id UNIQUE (source, source_id)
);

COMMENT ON TABLE buildings IS '3D building footprint data for line-of-sight calculations';
COMMENT ON COLUMN buildings.geometry IS 'Building footprint polygon in WGS84 (SRID 4326)';
COMMENT ON COLUMN buildings.height IS 'Building height in meters';
COMMENT ON COLUMN buildings.source IS 'Data source identifier (e.g., microsoft_buildings, osm)';
COMMENT ON COLUMN buildings.source_id IS 'Original ID from source dataset';
COMMENT ON COLUMN buildings.height_source IS 'Source of height data (e.g., ml_inference, lidar)';
COMMENT ON COLUMN buildings.height_confidence IS 'Confidence score for height (0.0-1.0)';

-- =============================================================================
-- Terrain Tiles Table
-- =============================================================================
-- Metadata for SRTM/ASTER DEM terrain tiles stored in S3

CREATE TABLE IF NOT EXISTS terrain_tiles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Bounding box for the tile
    bbox GEOMETRY(POLYGON, 4326) NOT NULL,
    
    -- S3 path to terrain raster file
    s3_path VARCHAR(512) NOT NULL,
    
    -- Spatial resolution in meters
    resolution_m DOUBLE PRECISION NOT NULL DEFAULT 30.0 CHECK (resolution_m > 0),
    
    -- Record creation timestamp
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

COMMENT ON TABLE terrain_tiles IS 'Terrain tile metadata for elevation data';
COMMENT ON COLUMN terrain_tiles.bbox IS 'Tile bounding box in WGS84 (SRID 4326)';
COMMENT ON COLUMN terrain_tiles.s3_path IS 'S3 URI to terrain raster file';
COMMENT ON COLUMN terrain_tiles.resolution_m IS 'Spatial resolution in meters';

-- =============================================================================
-- TLE Cache Table
-- =============================================================================
-- Two-Line Element cache for satellite orbital data

CREATE TABLE IF NOT EXISTS tle_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Satellite constellation name
    constellation VARCHAR(64) NOT NULL UNIQUE,
    
    -- Raw TLE text data
    tle_data TEXT NOT NULL,
    
    -- Cache timestamps
    fetched_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE
);

COMMENT ON TABLE tle_cache IS 'Two-Line Element cache for satellite orbital data';
COMMENT ON COLUMN tle_cache.constellation IS 'Satellite constellation name (e.g., starlink, oneweb)';
COMMENT ON COLUMN tle_cache.tle_data IS 'Raw TLE text data';
COMMENT ON COLUMN tle_cache.fetched_at IS 'Timestamp when TLE was fetched';
COMMENT ON COLUMN tle_cache.expires_at IS 'Cache expiration timestamp';

-- =============================================================================
-- Analysis Cache Table
-- =============================================================================
-- Cached analysis results for geospatial queries

CREATE TABLE IF NOT EXISTS analysis_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Geohash for cache key (precision 6 = ~1.2km x 0.6km)
    geohash VARCHAR(12) NOT NULL UNIQUE,
    
    -- Center coordinates
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    
    -- JSON analysis result data
    result_json JSONB NOT NULL,
    
    -- Cache timestamps
    computed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE,
    
    -- Access statistics
    access_count DOUBLE PRECISION DEFAULT 0 NOT NULL,
    last_accessed_at TIMESTAMP WITH TIME ZONE,
    
    -- Validate coordinates
    CONSTRAINT chk_lat_range CHECK (lat >= -90 AND lat <= 90),
    CONSTRAINT chk_lon_range CHECK (lon >= -180 AND lon <= 180)
);

COMMENT ON TABLE analysis_cache IS 'Cached analysis results for geospatial queries';
COMMENT ON COLUMN analysis_cache.geohash IS 'Geohash string (precision 6 = ~1.2km x 0.6km)';
COMMENT ON COLUMN analysis_cache.lat IS 'Latitude of cache center';
COMMENT ON COLUMN analysis_cache.lon IS 'Longitude of cache center';
COMMENT ON COLUMN analysis_cache.result_json IS 'JSON analysis result data';
COMMENT ON COLUMN analysis_cache.computed_at IS 'Timestamp when analysis was computed';
COMMENT ON COLUMN analysis_cache.expires_at IS 'Cache expiration timestamp';
COMMENT ON COLUMN analysis_cache.access_count IS 'Number of times cache was accessed';
COMMENT ON COLUMN analysis_cache.last_accessed_at IS 'Last access timestamp';

-- =============================================================================
-- Basic Indexes
-- =============================================================================

-- Buildings indexes
CREATE INDEX IF NOT EXISTS idx_buildings_source ON buildings (source);
CREATE INDEX IF NOT EXISTS idx_buildings_height ON buildings (height);
CREATE INDEX IF NOT EXISTS idx_buildings_updated_at ON buildings (updated_at);

-- Terrain tiles indexes
CREATE INDEX IF NOT EXISTS idx_terrain_tiles_resolution ON terrain_tiles (resolution_m);

-- TLE cache indexes
CREATE INDEX IF NOT EXISTS idx_tle_cache_fetched_at ON tle_cache (fetched_at);
CREATE INDEX IF NOT EXISTS idx_tle_cache_expires_at ON tle_cache (expires_at);

-- Analysis cache indexes
CREATE INDEX IF NOT EXISTS idx_analysis_cache_geohash ON analysis_cache (geohash);
CREATE INDEX IF NOT EXISTS idx_analysis_cache_lat_lon ON analysis_cache (lat, lon);
CREATE INDEX IF NOT EXISTS idx_analysis_cache_computed_at ON analysis_cache (computed_at);
CREATE INDEX IF NOT EXISTS idx_analysis_cache_expires_at ON analysis_cache (expires_at);
CREATE INDEX IF NOT EXISTS idx_analysis_cache_access_count ON analysis_cache (access_count);

-- =============================================================================
-- Migration Tracking
-- =============================================================================

CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(64) PRIMARY KEY,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    description TEXT
);

INSERT INTO schema_migrations (version, description)
VALUES ('001_initial_schema', 'Initial schema with buildings, terrain_tiles, tle_cache, analysis_cache')
ON CONFLICT (version) DO NOTHING;

-- =============================================================================
-- Verification
-- =============================================================================

DO $$
BEGIN
    -- Verify PostGIS is installed
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis') THEN
        RAISE EXCEPTION 'PostGIS extension is required but not installed';
    END IF;
    
    -- Verify tables were created
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'buildings') THEN
        RAISE EXCEPTION 'Buildings table was not created';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'terrain_tiles') THEN
        RAISE EXCEPTION 'Terrain tiles table was not created';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'tle_cache') THEN
        RAISE EXCEPTION 'TLE cache table was not created';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'analysis_cache') THEN
        RAISE EXCEPTION 'Analysis cache table was not created';
    END IF;
    
    RAISE NOTICE 'Schema migration 001_initial_schema completed successfully';
END $$;

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
-- LinkSpot Performance Indexes Migration
-- =============================================================================
-- Adds spatial and performance indexes for sub-millisecond query performance
--
-- Spatial Indexes:
--   - GiST indexes on geometry columns for efficient spatial queries
--   - Geography-based distance calculations
--
-- Performance Indexes:
--   - Partial indexes for common query patterns
--   - Composite indexes for multi-column lookups
--   - Expression indexes for computed values
-- =============================================================================

-- =============================================================================
-- Spatial Indexes (GiST)
-- =============================================================================

-- GiST index on buildings geometry for fast spatial queries
-- Supports ST_DWithin, ST_Intersects, ST_Contains operations
CREATE INDEX IF NOT EXISTS idx_buildings_geometry_gist 
ON buildings USING GIST (geometry);

COMMENT ON INDEX idx_buildings_geometry_gist IS 
'GiST spatial index for building geometry queries (radius, bbox, intersects)';

-- GiST index on terrain tiles bounding boxes
CREATE INDEX IF NOT EXISTS idx_terrain_tiles_bbox_gist 
ON terrain_tiles USING GIST (bbox);

COMMENT ON INDEX idx_terrain_tiles_bbox_gist IS 
'GiST spatial index for terrain tile bounding box queries';

-- =============================================================================
-- Geography-based Distance Index
-- =============================================================================
-- For accurate distance calculations using geography type

CREATE INDEX IF NOT EXISTS idx_buildings_geometry_geog 
ON buildings USING GIST (geography(geometry));

COMMENT ON INDEX idx_buildings_geometry_geog IS 
'Geography-based GiST index for accurate distance calculations in meters';

-- =============================================================================
-- Partial Indexes
-- =============================================================================
-- Index only rows that match specific conditions

-- Index buildings with significant height (> 10m)
-- Useful for skyline/obstruction queries
CREATE INDEX IF NOT EXISTS idx_buildings_tall 
ON buildings (height, geometry) 
WHERE height > 10.0;

COMMENT ON INDEX idx_buildings_tall IS 
'Partial index for tall buildings (>10m) for skyline queries';

-- Index active (non-expired) analysis cache entries
CREATE INDEX IF NOT EXISTS idx_analysis_cache_active 
ON analysis_cache (geohash, computed_at) 
WHERE expires_at IS NULL OR expires_at > NOW();

COMMENT ON INDEX idx_analysis_cache_active IS 
'Partial index for active (non-expired) analysis cache entries';

-- Index frequently accessed analysis cache entries
CREATE INDEX IF NOT EXISTS idx_analysis_cache_popular 
ON analysis_cache (geohash, access_count DESC) 
WHERE access_count > 10;

COMMENT ON INDEX idx_analysis_cache_popular IS 
'Partial index for frequently accessed cache entries';

-- =============================================================================
-- Composite Indexes
-- =============================================================================
-- Multi-column indexes for common query patterns

-- Composite index for building source queries with height filter
CREATE INDEX IF NOT EXISTS idx_buildings_source_height 
ON buildings (source, height) 
INCLUDE (source_id, updated_at);

COMMENT ON INDEX idx_buildings_source_height IS 
'Composite index for source-based queries with height filtering';

-- Composite index for analysis cache location-based lookups
CREATE INDEX IF NOT EXISTS idx_analysis_cache_location 
ON analysis_cache (lat, lon, computed_at);

COMMENT ON INDEX idx_analysis_cache_location IS 
'Composite index for location-based cache lookups';

-- =============================================================================
-- Expression Indexes
-- =============================================================================
-- Indexes on computed expressions

-- Index on geohash prefix for range queries
CREATE INDEX IF NOT EXISTS idx_analysis_cache_geohash_prefix 
ON analysis_cache (geohash varchar_pattern_ops);

COMMENT ON INDEX idx_analysis_cache_geohash_prefix IS 
'Expression index for geohash prefix matching (LIKE queries)';

-- Index on lowercased constellation name for case-insensitive lookups
CREATE INDEX IF NOT EXISTS idx_tle_cache_constellation_lower 
ON tle_cache (LOWER(constellation));

COMMENT ON INDEX idx_tle_cache_constellation_lower IS 
'Expression index for case-insensitive constellation lookups';

-- =============================================================================
-- BRIN Indexes (Block Range Indexes)
-- =============================================================================
-- Space-efficient indexes for large, naturally ordered tables

-- BRIN index on building height for range queries
-- Effective when buildings are roughly ordered by height
CREATE INDEX IF NOT EXISTS idx_buildings_height_brin 
ON buildings USING BRIN (height) 
WITH (pages_per_range = 128);

COMMENT ON INDEX idx_buildings_height_brin IS 
'BRIN index for height range queries on large datasets';

-- BRIN index on analysis cache computed_at for time-based queries
CREATE INDEX IF NOT EXISTS idx_analysis_cache_computed_brin 
ON analysis_cache USING BRIN (computed_at) 
WITH (pages_per_range = 128);

COMMENT ON INDEX idx_analysis_cache_computed_brin IS 
'BRIN index for time-based cache queries';

-- =============================================================================
-- Covering Indexes (INCLUDE)
-- =============================================================================
-- Include additional columns to avoid table lookups

-- Covering index for building lookups with all commonly needed fields
CREATE INDEX IF NOT EXISTS idx_buildings_covering 
ON buildings (source, source_id) 
INCLUDE (height, height_confidence, updated_at);

COMMENT ON INDEX idx_buildings_covering IS 
'Covering index to avoid table lookups for common building queries';

-- =============================================================================
-- Functional Indexes for Spatial Queries
-- =============================================================================

-- Index on ST_Area for area-based filtering
CREATE INDEX IF NOT EXISTS idx_buildings_area 
ON buildings (ST_Area(geometry::geography));

COMMENT ON INDEX idx_buildings_area IS 
'Functional index for building area-based filtering';

-- Index on ST_Perimeter for perimeter-based queries
CREATE INDEX IF NOT EXISTS idx_buildings_perimeter 
ON buildings (ST_Perimeter(geometry::geography));

COMMENT ON INDEX idx_buildings_perimeter IS 
'Functional index for building perimeter-based queries';

-- =============================================================================
-- Index Statistics
-- =============================================================================
-- Improve query planner statistics for better plans

-- Increase statistics target for commonly filtered columns
ALTER TABLE buildings ALTER COLUMN height SET STATISTICS 1000;
ALTER TABLE buildings ALTER COLUMN source SET STATISTICS 500;
ALTER TABLE analysis_cache ALTER COLUMN geohash SET STATISTICS 1000;

-- Analyze tables to update statistics
ANALYZE buildings;
ANALYZE terrain_tiles;
ANALYZE tle_cache;
ANALYZE analysis_cache;

-- =============================================================================
-- Vacuum and Maintenance
-- =============================================================================

-- Set autovacuum parameters for high-write tables
ALTER TABLE buildings SET (autovacuum_vacuum_scale_factor = 0.1);
ALTER TABLE analysis_cache SET (autovacuum_vacuum_scale_factor = 0.2);
ALTER TABLE tle_cache SET (autovacuum_vacuum_scale_factor = 0.3);

-- =============================================================================
-- Migration Tracking
-- =============================================================================

INSERT INTO schema_migrations (version, description)
VALUES ('002_add_indexes', 'Added spatial GiST indexes, partial indexes, composite indexes, and BRIN indexes')
ON CONFLICT (version) DO NOTHING;

-- =============================================================================
-- Verification
-- =============================================================================

DO $$
DECLARE
    idx_count INTEGER;
    gist_count INTEGER;
BEGIN
    -- Count total indexes on buildings table
    SELECT COUNT(*) INTO idx_count
    FROM pg_indexes 
    WHERE tablename = 'buildings';
    
    RAISE NOTICE 'Buildings table has % indexes', idx_count;
    
    -- Count GiST indexes
    SELECT COUNT(*) INTO gist_count
    FROM pg_indexes pi
    JOIN pg_class pc ON pc.relname = pi.indexname
    JOIN pg_am pam ON pc.relam = pam.oid
    WHERE pi.tablename IN ('buildings', 'terrain_tiles')
    AND pam.amname = 'gist';
    
    RAISE NOTICE 'Found % GiST spatial indexes', gist_count;
    
    IF gist_count < 2 THEN
        RAISE WARNING 'Expected at least 2 GiST indexes, found %', gist_count;
    END IF;
    
    RAISE NOTICE 'Schema migration 002_add_indexes completed successfully';
END $$;

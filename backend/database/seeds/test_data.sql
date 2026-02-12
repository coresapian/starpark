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
-- LinkSpot Test Data
-- =============================================================================
-- Sample data for testing the LinkSpot database
-- 
-- Locations:
--   - San Francisco Financial District (37.7946, -122.4020)
--   - SOMA District (37.7849, -122.4089)
--   - Mission District (37.7594, -122.4214)
-- =============================================================================

-- =============================================================================
-- Test Buildings - San Francisco Financial District
-- =============================================================================

INSERT INTO buildings (geometry, height, source, source_id, height_source, height_confidence) VALUES
-- Transamerica Pyramid area buildings
(ST_GeomFromText('POLYGON((-122.4028 37.7952, -122.4024 37.7952, -122.4024 37.7948, -122.4028 37.7948, -122.4028 37.7952))', 4326), 
 260.0, 'test_data', 'sf_transamerica', 'lidar', 0.95),

-- Salesforce Tower area
(ST_GeomFromText('POLYGON((-122.3967 37.7899, -122.3963 37.7899, -122.3963 37.7895, -122.3967 37.7895, -122.3967 37.7899))', 4326), 
 326.0, 'test_data', 'sf_salesforce_tower', 'lidar', 0.98),

-- 555 California Street
(ST_GeomFromText('POLYGON((-122.4036 37.7925, -122.4032 37.7925, -122.4032 37.7921, -122.4036 37.7921, -122.4036 37.7925))', 4326), 
 237.0, 'test_data', 'sf_555_california', 'lidar', 0.92),

-- One Rincon Hill
(ST_GeomFromText('POLYGON((-122.3958 37.7933, -122.3954 37.7933, -122.3954 37.7929, -122.3958 37.7929, -122.3958 37.7933))', 4326), 
 194.0, 'test_data', 'sf_one_rincon', 'lidar', 0.90),

-- Millennium Tower
(ST_GeomFromText('POLYGON((-122.3961 37.7906, -122.3957 37.7906, -122.3957 37.7902, -122.3961 37.7902, -122.3961 37.7906))', 4326), 
 196.0, 'test_data', 'sf_millennium', 'lidar', 0.88),

-- Medium-height office buildings
(ST_GeomFromText('POLYGON((-122.4010 37.7910, -122.4005 37.7910, -122.4005 37.7905, -122.4010 37.7905, -122.4010 37.7910))', 4326), 
 85.0, 'test_data', 'sf_office_01', 'ml_inference', 0.75),

(ST_GeomFromText('POLYGON((-122.4000 37.7915, -122.3995 37.7915, -122.3995 37.7910, -122.4000 37.7910, -122.4000 37.7915))', 4326), 
 62.0, 'test_data', 'sf_office_02', 'ml_inference', 0.72),

(ST_GeomFromText('POLYGON((-122.3990 37.7920, -122.3985 37.7920, -122.3985 37.7915, -122.3990 37.7915, -122.3990 37.7920))', 4326), 
 45.0, 'test_data', 'sf_office_03', 'ml_inference', 0.70),

-- Low-rise buildings
(ST_GeomFromText('POLYGON((-122.3980 37.7925, -122.3975 37.7925, -122.3975 37.7920, -122.3980 37.7920, -122.3980 37.7925))', 4326), 
 15.0, 'test_data', 'sf_lowrise_01', 'ml_inference', 0.65),

(ST_GeomFromText('POLYGON((-122.3970 37.7930, -122.3965 37.7930, -122.3965 37.7925, -122.3970 37.7925, -122.3970 37.7930))', 4326), 
 12.0, 'test_data', 'sf_lowrise_02', 'ml_inference', 0.60);

-- =============================================================================
-- Test Buildings - SOMA District
-- =============================================================================

INSERT INTO buildings (geometry, height, source, source_id, height_source, height_confidence) VALUES
-- Twitter/X Building
(ST_GeomFromText('POLYGON((-122.4167 37.7769, -122.4163 37.7769, -122.4163 37.7765, -122.4167 37.7765, -122.4167 37.7769))', 4326), 
 45.0, 'test_data', 'sf_twitter_building', 'lidar', 0.85),

-- Uber HQ
(ST_GeomFromText('POLYGON((-122.4180 37.7685, -122.4175 37.7685, -122.4175 37.7680, -122.4180 37.7680, -122.4180 37.7685))', 4326), 
 52.0, 'test_data', 'sf_uber_hq', 'lidar', 0.82),

-- Medium office buildings
(ST_GeomFromText('POLYGON((-122.4150 37.7780, -122.4145 37.7780, -122.4145 37.7775, -122.4150 37.7775, -122.4150 37.7780))', 4326), 
 38.0, 'test_data', 'sf_soma_office_01', 'ml_inference', 0.70),

(ST_GeomFromText('POLYGON((-122.4140 37.7790, -122.4135 37.7790, -122.4135 37.7785, -122.4140 37.7785, -122.4140 37.7790))', 4326), 
 42.0, 'test_data', 'sf_soma_office_02', 'ml_inference', 0.68),

-- Residential buildings
(ST_GeomFromText('POLYGON((-122.4130 37.7800, -122.4125 37.7800, -122.4125 37.7795, -122.4130 37.7795, -122.4130 37.7800))', 4326), 
 28.0, 'test_data', 'sf_soma_res_01', 'ml_inference', 0.65),

(ST_GeomFromText('POLYGON((-122.4120 37.7810, -122.4115 37.7810, -122.4115 37.7805, -122.4120 37.7805, -122.4120 37.7810))', 4326), 
 32.0, 'test_data', 'sf_soma_res_02', 'ml_inference', 0.63);

-- =============================================================================
-- Test Buildings - Mission District
-- =============================================================================

INSERT INTO buildings (geometry, height, source, source_id, height_source, height_confidence) VALUES
-- Mission District mixed-use
(ST_GeomFromText('POLYGON((-122.4214 37.7594, -122.4210 37.7594, -122.4210 37.7590, -122.4214 37.7590, -122.4214 37.7594))', 4326), 
 18.0, 'test_data', 'sf_mission_01', 'ml_inference', 0.60),

(ST_GeomFromText('POLYGON((-122.4204 37.7604, -122.4200 37.7604, -122.4200 37.7600, -122.4204 37.7600, -122.4204 37.7604))', 4326), 
 22.0, 'test_data', 'sf_mission_02', 'ml_inference', 0.58),

(ST_GeomFromText('POLYGON((-122.4194 37.7614, -122.4190 37.7614, -122.4190 37.7610, -122.4194 37.7610, -122.4194 37.7614))', 4326), 
 15.0, 'test_data', 'sf_mission_03', 'ml_inference', 0.55),

-- Victorian houses (low rise)
(ST_GeomFromText('POLYGON((-122.4184 37.7624, -122.4180 37.7624, -122.4180 37.7620, -122.4184 37.7620, -122.4184 37.7624))', 4326), 
 12.0, 'test_data', 'sf_victorian_01', 'ml_inference', 0.50),

(ST_GeomFromText('POLYGON((-122.4174 37.7634, -122.4170 37.7634, -122.4170 37.7630, -122.4174 37.7630, -122.4174 37.7634))', 4326), 
 10.0, 'test_data', 'sf_victorian_02', 'ml_inference', 0.48);

-- =============================================================================
-- Test Terrain Tiles
-- =============================================================================

INSERT INTO terrain_tiles (bbox, s3_path, resolution_m) VALUES
-- San Francisco SRTM tile
(ST_GeomFromText('POLYGON((-123.0 37.0, -122.0 37.0, -122.0 38.0, -123.0 38.0, -123.0 37.0))', 4326),
 's3://linkspot-terrain/srtm/n37w123.tif', 30.0),

-- Higher resolution tile for downtown SF
(ST_GeomFromText('POLYGON((-122.5 37.5, -122.0 37.5, -122.0 38.0, -122.5 38.0, -122.5 37.5))', 4326),
 's3://linkspot-terrain/aster/n37w123_hires.tif', 10.0);

-- =============================================================================
-- Test TLE Cache
-- =============================================================================

INSERT INTO tle_cache (constellation, tle_data, fetched_at, expires_at) VALUES
('starlink', 
'STARLINK-1007
1 44713U 19074A   24001.50000000  .00010000  00000-0  12345-3 0  9992
2 44713  53.0000  75.0000 0001000  90.0000 270.0000 15.00000000 12345
STARLINK-1008
1 44714U 19074B   24001.50000000  .00010000  00000-0  12345-3 0  9993
2 44714  53.0000  75.1000 0001000  90.0000 270.1000 15.00000000 12346',
 NOW(),
 NOW() + INTERVAL '4 hours'),

('oneweb', 
'ONEWEB-001
1 45131U 20008A   24001.50000000  .00005000  00000-0  67890-4 0  9994
2 45131  87.9000  45.0000 0001000  45.0000 315.0000 13.00000000 12347
ONEWEB-002
1 45132U 20008B   24001.50000000  .00005000  00000-0  67890-4 0  9995
2 45132  87.9000  45.1000 0001000  45.0000 315.1000 13.00000000 12348',
 NOW(),
 NOW() + INTERVAL '4 hours');

-- =============================================================================
-- Test Analysis Cache
-- =============================================================================

INSERT INTO analysis_cache (geohash, lat, lon, result_json, computed_at, expires_at, access_count) VALUES
-- Financial District analysis cache
('dqcjqc', 37.7946, -122.4020, 
'{
    "location": {"lat": 37.7946, "lon": -122.4020},
    "visibility_score": 0.75,
    "obstructions": [
        {"building_id": "sf_transamerica", "azimuth": 45, "elevation": 35, "distance": 150},
        {"building_id": "sf_555_california", "azimuth": 120, "elevation": 28, "distance": 200}
    ],
    "satellite_passes": [
        {"constellation": "starlink", "count": 12, "avg_elevation": 45},
        {"constellation": "oneweb", "count": 3, "avg_elevation": 52}
    ],
    "recommended_directions": ["N", "NE", "NW"],
    "computed_at": "2024-01-01T00:00:00Z"
}'::jsonb,
 NOW(),
 NOW() + INTERVAL '24 hours',
 15),

-- SOMA analysis cache
('dqcjqf', 37.7849, -122.4089,
'{
    "location": {"lat": 37.7849, "lon": -122.4089},
    "visibility_score": 0.82,
    "obstructions": [
        {"building_id": "sf_twitter_building", "azimuth": 90, "elevation": 15, "distance": 80}
    ],
    "satellite_passes": [
        {"constellation": "starlink", "count": 15, "avg_elevation": 48},
        {"constellation": "oneweb", "count": 4, "avg_elevation": 55}
    ],
    "recommended_directions": ["N", "S", "E", "W"],
    "computed_at": "2024-01-01T00:00:00Z"
}'::jsonb,
 NOW(),
 NOW() + INTERVAL '24 hours',
 8),

-- Mission District analysis cache
('dqcjqb', 37.7594, -122.4214,
'{
    "location": {"lat": 37.7594, "lon": -122.4214},
    "visibility_score": 0.91,
    "obstructions": [],
    "satellite_passes": [
        {"constellation": "starlink", "count": 18, "avg_elevation": 50},
        {"constellation": "oneweb", "count": 5, "avg_elevation": 58}
    ],
    "recommended_directions": ["N", "NE", "E", "SE", "S", "SW", "W", "NW"],
    "computed_at": "2024-01-01T00:00:00Z"
}'::jsonb,
 NOW(),
 NOW() + INTERVAL '24 hours',
 25);

-- =============================================================================
-- Verification Query
-- =============================================================================

DO $$
DECLARE
    building_count INTEGER;
    terrain_count INTEGER;
    tle_count INTEGER;
    analysis_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO building_count FROM buildings WHERE source = 'test_data';
    SELECT COUNT(*) INTO terrain_count FROM terrain_tiles;
    SELECT COUNT(*) INTO tle_count FROM tle_cache;
    SELECT COUNT(*) INTO analysis_count FROM analysis_cache;
    
    RAISE NOTICE 'Test data loaded:';
    RAISE NOTICE '  - Buildings: %', building_count;
    RAISE NOTICE '  - Terrain tiles: %', terrain_count;
    RAISE NOTICE '  - TLE cache entries: %', tle_count;
    RAISE NOTICE '  - Analysis cache entries: %', analysis_count;
    
    -- Verify spatial data
    IF building_count = 0 THEN
        RAISE WARNING 'No test buildings loaded!';
    END IF;
    
    RAISE NOTICE 'Test data seeding completed successfully';
END $$;

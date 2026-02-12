#!/bin/bash
# =============================================================================
# LinkSpot Database Initialization Script
# Runs inside PostgreSQL container on first startup
# =============================================================================

set -e

echo "=========================================="
echo "LinkSpot Database Initialization"
echo "=========================================="

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL to be ready..."
until pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"; do
    echo "PostgreSQL is not ready yet. Waiting..."
    sleep 2
done
echo "PostgreSQL is ready!"

# =============================================================================
# Create Extensions
# =============================================================================

echo "Creating PostGIS extensions..."

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Enable PostGIS extension for spatial data
    CREATE EXTENSION IF NOT EXISTS postgis;
    
    -- Enable PostGIS topology extension
    CREATE EXTENSION IF NOT EXISTS postgis_topology;
    
    -- Enable additional spatial functions
    CREATE EXTENSION IF NOT EXISTS postgis_raster;
    
    -- Verify installation
    SELECT PostGIS_Version();
EOSQL

echo "PostGIS extensions created successfully!"

# =============================================================================
# Create Application Schema
# =============================================================================

echo "Creating application schema..."

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Create schema for LinkSpot application
    CREATE SCHEMA IF NOT EXISTS linkspot;
    
    -- Set search path
    ALTER DATABASE "$POSTGRES_DB" SET search_path TO linkspot, public;
    
    -- Grant permissions
    GRANT ALL PRIVILEGES ON SCHEMA linkspot TO "$POSTGRES_USER";
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA linkspot TO "$POSTGRES_USER";
    GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA linkspot TO "$POSTGRES_USER";
EOSQL

echo "Application schema created!"

# =============================================================================
# Create Core Tables
# =============================================================================

echo "Creating core database tables..."

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Set search path
    SET search_path TO linkspot, public;
    
    -- Buildings table with spatial index
    CREATE TABLE IF NOT EXISTS buildings (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255),
        height_meters DECIMAL(10, 2),
        floors INTEGER,
        geom GEOMETRY(POLYGON, 4326),
        properties JSONB DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    -- Create spatial index on buildings
    CREATE INDEX IF NOT EXISTS idx_buildings_geom 
        ON buildings USING GIST(geom);
    
    -- Create index on height for quick filtering
    CREATE INDEX IF NOT EXISTS idx_buildings_height 
        ON buildings(height_meters);
    
    -- Satellite TLE data table
    CREATE TABLE IF NOT EXISTS satellite_tle (
        id SERIAL PRIMARY KEY,
        norad_id INTEGER UNIQUE NOT NULL,
        name VARCHAR(255) NOT NULL,
        line1 VARCHAR(100) NOT NULL,
        line2 VARCHAR(100) NOT NULL,
        epoch TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        raw_data TEXT
    );
    
    -- Create index on NORAD ID
    CREATE INDEX IF NOT EXISTS idx_satellite_norad 
        ON satellite_tle(norad_id);
    
    -- Satellite visibility calculations cache
    CREATE TABLE IF NOT EXISTS satellite_visibility (
        id SERIAL PRIMARY KEY,
        building_id INTEGER REFERENCES buildings(id) ON DELETE CASCADE,
        norad_id INTEGER REFERENCES satellite_tle(norad_id) ON DELETE CASCADE,
        visible BOOLEAN DEFAULT FALSE,
        elevation DECIMAL(5, 2),
        azimuth DECIMAL(5, 2),
        range_km DECIMAL(10, 2),
        calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(building_id, norad_id)
    );
    
    -- Create index for visibility queries
    CREATE INDEX IF NOT EXISTS idx_visibility_building 
        ON satellite_visibility(building_id);
    CREATE INDEX IF NOT EXISTS idx_visibility_visible 
        ON satellite_visibility(visible) WHERE visible = TRUE;
    
    -- Link calculations cache
    CREATE TABLE IF NOT EXISTS link_calculations (
        id SERIAL PRIMARY KEY,
        building_a_id INTEGER REFERENCES buildings(id) ON DELETE CASCADE,
        building_b_id INTEGER REFERENCES buildings(id) ON DELETE CASCADE,
        satellite_count INTEGER DEFAULT 0,
        common_satellites INTEGER[] DEFAULT '{}',
        link_quality DECIMAL(3, 2),
        calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(building_a_id, building_b_id)
    );
    
    -- Create index for link queries
    CREATE INDEX IF NOT EXISTS idx_links_building_a 
        ON link_calculations(building_a_id);
    CREATE INDEX IF NOT EXISTS idx_links_building_b 
        ON link_calculations(building_b_id);
    CREATE INDEX IF NOT EXISTS idx_links_quality 
        ON link_calculations(link_quality);
    
    -- Application settings table
    CREATE TABLE IF NOT EXISTS app_settings (
        key VARCHAR(100) PRIMARY KEY,
        value TEXT,
        description TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    -- Insert default settings
    INSERT INTO app_settings (key, value, description) VALUES
        ('min_elevation', '25.0', 'Minimum elevation angle for satellite visibility (degrees)'),
        ('satellite_threshold', '4', 'Minimum number of satellites for link calculation'),
        ('tle_update_interval', '14400', 'TLE data update interval (seconds)'),
        ('building_cache_ttl', '86400', 'Building data cache TTL (seconds)')
    ON CONFLICT (key) DO NOTHING;
    
    -- Request log for analytics (optional)
    CREATE TABLE IF NOT EXISTS request_logs (
        id SERIAL PRIMARY KEY,
        endpoint VARCHAR(255),
        method VARCHAR(10),
        params JSONB,
        response_time_ms INTEGER,
        status_code INTEGER,
        client_ip INET,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    -- Create index for analytics queries
    CREATE INDEX IF NOT EXISTS idx_logs_created 
        ON request_logs(created_at);
    CREATE INDEX IF NOT EXISTS idx_logs_endpoint 
        ON request_logs(endpoint);
    
    -- Grant permissions on all tables
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA linkspot TO "$POSTGRES_USER";
    GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA linkspot TO "$POSTGRES_USER";
    
    -- Grant permissions on future tables
    ALTER DEFAULT PRIVILEGES IN SCHEMA linkspot 
        GRANT ALL ON TABLES TO "$POSTGRES_USER";
    ALTER DEFAULT PRIVILEGES IN SCHEMA linkspot 
        GRANT ALL ON SEQUENCES TO "$POSTGRES_USER";
    
EOSQL

echo "Core tables created successfully!"

# =============================================================================
# Create Functions and Triggers
# =============================================================================

echo "Creating database functions..."

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Set search path
    SET search_path TO linkspot, public;
    
    -- Function to update updated_at timestamp
    CREATE OR REPLACE FUNCTION update_updated_at_column()
    RETURNS TRIGGER AS \$\$
    BEGIN
        NEW.updated_at = CURRENT_TIMESTAMP;
        RETURN NEW;
    END;
    \$\$ language 'plpgsql';
    
    -- Create triggers for updated_at
    DROP TRIGGER IF EXISTS update_buildings_updated_at ON buildings;
    CREATE TRIGGER update_buildings_updated_at
        BEFORE UPDATE ON buildings
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    
    DROP TRIGGER IF EXISTS update_satellite_tle_updated_at ON satellite_tle;
    CREATE TRIGGER update_satellite_tle_updated_at
        BEFORE UPDATE ON satellite_tle
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    
    DROP TRIGGER IF EXISTS update_app_settings_updated_at ON app_settings;
    CREATE TRIGGER update_app_settings_updated_at
        BEFORE UPDATE ON app_settings
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    
EOSQL

echo "Database functions created!"

# =============================================================================
# Optional: Seed Test Data
# =============================================================================

if [ "$SEED_TEST_DATA" = "true" ]; then
    echo "Seeding test data..."
    
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
        SET search_path TO linkspot, public;
        
        -- Insert sample buildings (New York area)
        INSERT INTO buildings (name, height_meters, floors, geom, properties) VALUES
            ('One World Trade Center', 541.3, 104, 
             ST_GeomFromText('POLYGON((-74.0133 40.7127, -74.0130 40.7127, -74.0130 40.7130, -74.0133 40.7130, -74.0133 40.7127))', 4326),
             '{"city": "New York", "type": "office"}'),
            ('Empire State Building', 443.2, 102, 
             ST_GeomFromText('POLYGON((-73.9857 40.7484, -73.9854 40.7484, -73.9854 40.7487, -73.9857 40.7487, -73.9857 40.7484))', 4326),
             '{"city": "New York", "type": "office"}'),
            ('Chrysler Building', 318.9, 77, 
             ST_GeomFromText('POLYGON((-73.9754 40.7517, -73.9751 40.7517, -73.9751 40.7520, -73.9754 40.7520, -73.9754 40.7517))', 4326),
             '{"city": "New York", "type": "office"}')
        ON CONFLICT DO NOTHING;
        
        -- Insert sample satellite TLE data (Starlink satellites)
        INSERT INTO satellite_tle (norad_id, name, line1, line2, epoch) VALUES
            (44713, 'STARLINK-24', 
             '1 44713U 19074A   24001.50000000  .00001234  00000-0  12345-3 0  9999',
             '2 44713  53.0000  60.0000 0001000  90.0000 270.0000 15.50000000 12345',
             '2024-01-01 12:00:00'),
            (44714, 'STARLINK-25', 
             '1 44714U 19074B   24001.50000000  .00001234  00000-0  12345-3 0  9999',
             '2 44714  53.0000  75.0000 0001000  90.0000 270.0000 15.50000000 12346',
             '2024-01-01 12:00:00')
        ON CONFLICT DO NOTHING;
        
EOSQL
    
    echo "Test data seeded!"
fi

# =============================================================================
# Verify Installation
# =============================================================================

echo ""
echo "Verifying database setup..."

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SET search_path TO linkspot, public;
    
    -- Show tables
    SELECT 'Tables created:' as info;
    SELECT tablename FROM pg_tables WHERE schemaname = 'linkspot';
    
    -- Show extensions
    SELECT 'PostGIS version:' as info, PostGIS_Version() as version;
    
    -- Count records
    SELECT 'Buildings count:' as info, COUNT(*) as count FROM buildings;
    SELECT 'Satellites count:' as info, COUNT(*) as count FROM satellite_tle;
    
EOSQL

echo ""
echo "=========================================="
echo "Database initialization complete!"
echo "=========================================="

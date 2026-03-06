/**
 * LinkSpot Route Renderer
 * Draws route segments, waypoints, and dead zones on Leaflet.
 */
class RouteRenderer {
    constructor() {
        this.map = null;
        this.routeLayer = null;
        this.waypointLayer = null;
        this.deadZoneLayer = null;
    }

    /**
     * @param {L.Map} map
     */
    init(map) {
        if (this.map && this.map !== map) {
            this.clear();
        }
        this.map = map;
    }

    /**
     * Clear all route layers.
     */
    clear() {
        if (!this.map) return;

        if (this.routeLayer) {
            this.map.removeLayer(this.routeLayer);
            this.routeLayer = null;
        }
        if (this.waypointLayer) {
            this.map.removeLayer(this.waypointLayer);
            this.waypointLayer = null;
        }
        if (this.deadZoneLayer) {
            this.map.removeLayer(this.deadZoneLayer);
            this.deadZoneLayer = null;
        }
        // TODO: Reconcile this renderer with legacy LayerGroup paths if map instances are hot-swapped.
    }

    /**
     * Render route geometry with per-segment signal classes.
     * @param {Object} routeGeojson
     */
    renderRoute(routeGeojson) {
        if (!this.map || !routeGeojson) return;
        if (!Array.isArray(routeGeojson.features)) return;
        const validFeatures = routeGeojson.features.filter((feature) => (
            feature &&
            feature.type === 'Feature' &&
            feature.geometry &&
            (feature.geometry.type === 'LineString' || feature.geometry.type === 'MultiLineString')
        ));
        if (validFeatures.length === 0) return;

        this.routeLayer = L.geoJSON({ type: 'FeatureCollection', features: validFeatures }, {
            style: (feature) => this._segmentStyle(feature?.properties?.signal),
            onEachFeature: (feature, layer) => {
                const props = feature.properties || {};
                const signal = String(props.signal || 'dead').toUpperCase();
                const visible = props.visible_satellites ?? 0;
                const total = props.total_satellites ?? 0;
                layer.bindTooltip(`<strong>${signal}</strong><br>${visible}/${total} satellites`);
            }
        }).addTo(this.map);
    }

    /**
     * Render waypoint markers.
     * @param {Array} waypoints
     */
    renderWaypoints(waypoints = []) {
        if (!this.map) return;

        this.waypointLayer = L.layerGroup();
        const seen = new Set();
        const sorted = (Array.isArray(waypoints) ? waypoints : [])
            .filter((wp) => Number.isFinite(Number(wp.lat)) && Number.isFinite(Number(wp.lon)))
            .sort((a, b) => Number(a.eta_seconds || 0) - Number(b.eta_seconds || 0));

        sorted.forEach((wp) => {
            const dedupeId = `${wp.id || 'wp'}:${Number(wp.lat).toFixed(6)}:${Number(wp.lon).toFixed(6)}`;
            if (seen.has(dedupeId)) return;
            seen.add(dedupeId);
            const marker = L.circleMarker([wp.lat, wp.lon], {
                radius: 7,
                color: '#ffffff',
                weight: 2,
                fillColor: this._zoneColor(wp.zone),
                fillOpacity: 0.95
            });

            const etaMin = wp.eta_seconds ? Math.round(wp.eta_seconds / 60) : 0;
            marker.bindPopup(
                `<strong>${this._escape(wp.name || wp.id || 'Waypoint')}</strong><br>` +
                `Coverage: ${Math.round(wp.coverage_pct || 0)}%<br>` +
                `Sats: ${wp.visible_satellites || 0}/${wp.total_satellites || 0}<br>` +
                `ETA: ${etaMin} min`
            );

            marker.addTo(this.waypointLayer);
        });

        this.waypointLayer.addTo(this.map);
    }

    /**
     * Render dead-zone line overlays.
     * @param {Array} deadZones
     */
    renderDeadZones(deadZones = []) {
        if (!this.map) return;

        this.deadZoneLayer = L.layerGroup();
        (Array.isArray(deadZones) ? deadZones : []).forEach((dz) => {
            const line = L.polyline(
                [[dz.start_lat, dz.start_lon], [dz.end_lat, dz.end_lon]],
                {
                    color: '#ef4444',
                    weight: 6,
                    opacity: 0.9,
                    dashArray: '8 8'
                }
            );

            const km = Number(dz.length_m || 0) / 1000;
            line.bindTooltip(`<strong>Dead Zone</strong><br>Length: ${km.toFixed(2)} km`);
            line.addTo(this.deadZoneLayer);
        });

        this.deadZoneLayer.addTo(this.map);
    }

    /**
     * Bring route layers to front and fit map bounds.
     */
    finalizeView() {
        if (this.routeLayer && this.routeLayer.getBounds().isValid()) {
            this.map.fitBounds(this.routeLayer.getBounds(), {
                padding: [36, 36],
                maxZoom: 15
            });
        }

        if (this.routeLayer) this.routeLayer.bringToFront();
        if (this.deadZoneLayer) this.deadZoneLayer.bringToFront();
        if (this.waypointLayer) this.waypointLayer.bringToFront();
    }

    _segmentStyle(signal) {
        const colors = {
            clear: '#2e8b57',
            marginal: '#d4a017',
            dead: '#c0392b'
        };

        return {
            color: colors[String(signal || '').toLowerCase()] || '#64748b',
            weight: 5,
            opacity: 0.9,
            lineCap: 'round',
            lineJoin: 'round'
        };
    }

    _zoneColor(zone) {
        const key = String(zone || '').toUpperCase();
        if (key.includes('EXCELLENT') || key.includes('GOOD') || key === 'CLEAR') return '#2e8b57';
        if (key.includes('FAIR') || key.includes('MARGINAL')) return '#d4a017';
        return '#c0392b';
    }

    _escape(text) {
        const div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
    }
}

if (typeof window !== 'undefined') {
    window.RouteRenderer = RouteRenderer;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { RouteRenderer };
}

/**
 * LinkSpot Anymap Bridge
 * Adapts the anymap-ts LeafletRenderer for standalone web application usage
 * without requiring the anywidget/Jupyter notebook infrastructure.
 */

import { LeafletRenderer } from "anymap-ts/src/leaflet/LeafletRenderer";
import * as L from "leaflet/dist/leaflet-src.esm.js";
import "leaflet/dist/leaflet.css";

/**
 * Standalone model adapter implementing the MapWidgetModel interface
 * required by anymap-ts BaseMapRenderer. Stores state locally instead
 * of syncing with a Python backend through anywidget.
 */
class StandaloneModel {
    constructor(initialState = {}) {
        this._state = {
            center: [-74.006, 40.7128], // [lng, lat] - anymap-ts convention
            zoom: 16,
            width: "100%",
            height: "100%",
            style: "",
            bearing: 0,
            pitch: 0,
            _js_calls: [],
            _js_events: [],
            _clicked_point: null,
            _bounds: null,
            _layers: {},
            _sources: {},
            _controls: {},
            _draw_data: null,
            ...initialState,
        };
        this._listeners = {};
    }

    get(key) {
        return this._state[key];
    }

    set(key, value) {
        this._state[key] = value;
        const event = `change:${key}`;
        if (this._listeners[event]) {
            this._listeners[event].forEach((cb) => {
                try {
                    cb();
                } catch (e) {
                    console.error(`[AnymapBridge] Listener error for ${event}:`, e);
                }
            });
        }
    }

    on(event, callback) {
        if (!this._listeners[event]) {
            this._listeners[event] = [];
        }
        this._listeners[event].push(callback);
    }

    off(event, callback) {
        if (this._listeners[event]) {
            this._listeners[event] = this._listeners[event].filter(
                (cb) => cb !== callback
            );
        }
    }

    save_changes() {
        // No-op for standalone usage
    }
}

/**
 * Bridge class that wraps anymap-ts LeafletRenderer for use in the
 * LinkSpot web application. Provides a clean API for map operations
 * while leveraging anymap-ts for map lifecycle, basemaps, and controls.
 */
class AnymapBridge {
    /**
     * @param {string} containerId - DOM element ID for the map container
     * @param {Object} options - Map configuration
     * @param {number} options.lat - Initial latitude
     * @param {number} options.lon - Initial longitude
     * @param {number} options.zoom - Initial zoom level
     */
    constructor(containerId, options = {}) {
        this.containerId = containerId;
        this.options = options;
        this.renderer = null;
        this.model = null;
        this._layers = new Map(); // name -> L.Layer
        this._eventHandlers = {}; // event -> [callback]
        this._callId = 0;
    }

    /**
     * Initialize the map
     */
    async init() {
        const lat = this.options.lat || 40.7128;
        const lon = this.options.lon || -74.006;
        const zoom = this.options.zoom || 16;

        this.model = new StandaloneModel({
            center: [lon, lat], // anymap-ts uses [lng, lat]
            zoom: zoom,
            width: "100%",
            height: "100%",
        });

        const container = document.getElementById(this.containerId);
        if (!container) {
            throw new Error(`Container element '${this.containerId}' not found`);
        }

        this.renderer = new LeafletRenderer(this.model, container);
        await this.renderer.initialize();

        // Access the underlying Leaflet map for custom operations
        this._leafletMap = this.renderer.map;

        // Use Canvas renderer for performance
        if (this._leafletMap) {
            this._leafletMap.options.renderer = L.canvas();
        }

        // Add attribution control (anymap-ts renderer disables it by default)
        L.control.attribution({
            prefix: false,
        }).addTo(this._leafletMap);

        // Set up internal event forwarding
        this._setupEventForwarding();

        // Add default dark-themed basemap tile layer
        this._addDefaultBasemap();

        return this;
    }

    /**
     * Add the CartoDB Dark basemap used by LinkSpot
     * @private
     */
    _addDefaultBasemap() {
        if (!this._leafletMap) return;

        L.tileLayer(
            "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
            {
                attribution:
                    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> ' +
                    'contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
                subdomains: "abcd",
                maxZoom: 20,
            }
        ).addTo(this._leafletMap);
    }

    /**
     * Forward Leaflet map events to registered handlers
     * @private
     */
    _setupEventForwarding() {
        if (!this._leafletMap) return;

        this._leafletMap.on("moveend", () => {
            this._fireEvent("moveend", this.getCenter());
        });

        this._leafletMap.on("zoomend", () => {
            this._fireEvent("zoomend", { zoom: this._leafletMap.getZoom() });
        });

        this._leafletMap.on("click", (e) => {
            this._fireEvent("click", {
                lat: e.latlng.lat,
                lon: e.latlng.lng,
            });
        });
    }

    /**
     * Fire an event to registered handlers
     * @private
     */
    _fireEvent(event, data) {
        if (this._eventHandlers[event]) {
            this._eventHandlers[event].forEach((cb) => {
                try {
                    cb(data);
                } catch (e) {
                    console.error(`[AnymapBridge] Event handler error:`, e);
                }
            });
        }
    }

    // ========================
    // Navigation
    // ========================

    /**
     * Set the map view to a position and zoom level
     * @param {number} lat - Latitude
     * @param {number} lon - Longitude
     * @param {number} zoom - Zoom level
     */
    setView(lat, lon, zoom) {
        if (this._leafletMap) {
            this._leafletMap.setView([lat, lon], zoom);
        }
    }

    /**
     * Animate to a position
     * @param {number} lat - Latitude
     * @param {number} lon - Longitude
     * @param {number} zoom - Zoom level
     */
    flyTo(lat, lon, zoom) {
        if (this._leafletMap) {
            this._leafletMap.flyTo([lat, lon], zoom);
        }
    }

    /**
     * Get the current map center
     * @returns {{lat: number, lon: number}}
     */
    getCenter() {
        if (!this._leafletMap) return { lat: 0, lon: 0 };
        const center = this._leafletMap.getCenter();
        return { lat: center.lat, lon: center.lng };
    }

    /**
     * Get the current zoom level
     * @returns {number}
     */
    getZoom() {
        if (!this._leafletMap) return 0;
        return this._leafletMap.getZoom();
    }

    // ========================
    // Layers
    // ========================

    /**
     * Add a GeoJSON layer with full Leaflet feature support
     * @param {string} name - Layer identifier
     * @param {Object} geojsonData - GeoJSON FeatureCollection
     * @param {Object|Function} style - Style object or per-feature style function
     * @param {Function} [onEachFeature] - Callback for each feature (feature, layer)
     * @returns {Object} The created Leaflet layer
     */
    addGeoJSON(name, geojsonData, style, onEachFeature) {
        // Remove existing layer with same name
        this.removeLayer(name);

        if (!this._leafletMap || !geojsonData) return null;

        const layerOptions = {};

        if (typeof style === "function") {
            layerOptions.style = style;
        } else if (style) {
            layerOptions.style = () => style;
        }

        if (onEachFeature) {
            layerOptions.onEachFeature = onEachFeature;
        }

        const layer = L.geoJSON(geojsonData, layerOptions).addTo(
            this._leafletMap
        );
        this._layers.set(name, layer);
        return layer;
    }

    /**
     * Remove a layer by name
     * @param {string} name - Layer identifier
     */
    removeLayer(name) {
        const layer = this._layers.get(name);
        if (layer && this._leafletMap) {
            this._leafletMap.removeLayer(layer);
            this._layers.delete(name);
        }
    }

    /**
     * Bring a layer to the back of the stack
     * @param {string} name - Layer identifier
     */
    bringToBack(name) {
        const layer = this._layers.get(name);
        if (layer && layer.bringToBack) {
            layer.bringToBack();
        }
    }

    /**
     * Check if a named layer exists
     * @param {string} name - Layer identifier
     * @returns {boolean}
     */
    hasLayer(name) {
        return this._layers.has(name);
    }

    // ========================
    // Markers
    // ========================

    /**
     * Add a marker to the map
     * @param {string} name - Marker identifier
     * @param {number} lat - Latitude
     * @param {number} lon - Longitude
     * @param {Object} [options] - Marker options
     * @param {string} [options.popup] - Popup content
     * @param {boolean} [options.openPopup] - Whether to open popup immediately
     * @returns {Object} The created Leaflet marker
     */
    addMarker(name, lat, lon, options = {}) {
        this.removeLayer(name);

        if (!this._leafletMap) return null;

        const marker = L.marker([lat, lon]).addTo(this._leafletMap);

        if (options.popup) {
            marker.bindPopup(options.popup);
            if (options.openPopup) {
                marker.openPopup();
            }
        }

        this._layers.set(name, marker);
        return marker;
    }

    // ========================
    // Controls
    // ========================

    /**
     * Add a zoom control
     * @param {string} position - Control position (e.g. 'bottomright')
     */
    addZoomControl(position = "bottomright") {
        if (!this._leafletMap) return;
        L.control.zoom({ position }).addTo(this._leafletMap);
    }

    // ========================
    // Events
    // ========================

    /**
     * Register an event handler
     * @param {string} event - Event name (moveend, zoomend, click)
     * @param {Function} callback - Event handler
     */
    on(event, callback) {
        if (!this._eventHandlers[event]) {
            this._eventHandlers[event] = [];
        }
        this._eventHandlers[event].push(callback);
    }

    /**
     * Remove an event handler
     * @param {string} event - Event name
     * @param {Function} callback - Event handler to remove
     */
    off(event, callback) {
        if (this._eventHandlers[event]) {
            this._eventHandlers[event] = this._eventHandlers[event].filter(
                (cb) => cb !== callback
            );
        }
    }

    // ========================
    // Utility
    // ========================

    /**
     * Invalidate map size (call after container resize)
     */
    invalidateSize() {
        if (this._leafletMap) {
            this._leafletMap.invalidateSize();
        }
    }

    /**
     * Get the underlying Leaflet map instance for advanced operations
     * @returns {Object} Leaflet map instance
     */
    getLeafletMap() {
        return this._leafletMap;
    }

    /**
     * Get the Leaflet library reference
     * @returns {Object} Leaflet library (L)
     */
    static getLeaflet() {
        return L;
    }

    // ========================
    // Cleanup
    // ========================

    /**
     * Destroy the map and clean up resources
     */
    destroy() {
        // Remove all tracked layers
        for (const [name] of this._layers) {
            this.removeLayer(name);
        }

        // Destroy the renderer (handles map removal)
        if (this.renderer) {
            this.renderer.destroy();
            this.renderer = null;
        }

        this._leafletMap = null;
        this.model = null;
        this._eventHandlers = {};
    }
}

// Export for IIFE global access
export { AnymapBridge, L };

/**
 * LinkSpot - Main Application
 * Interactive heat map visualization for satellite visibility analysis
 * @version 1.0.0
 */

/**
 * Main LinkSpot Application Class
 * Manages map, heat map rendering, user interactions, and UI state
 */
class LinkSpotApp {
    /**
     * Create LinkSpotApp instance
     * @param {Object} options - Configuration options
     * @param {string} options.apiBaseURL - Base URL for API
     * @param {Object} options.initialPosition - Initial map position {lat, lon, zoom}
     * @param {number} options.gridResolution - Heat map grid resolution in meters
     * @param {number} options.heatMapRadius - Default heat map radius in meters
     */
    constructor(options = {}) {
        // Configuration
        this.config = {
            apiBaseURL: options.apiBaseURL || '/api/v1',
            initialPosition: options.initialPosition || { lat: 39.8283, lon: -98.5795, zoom: 4 },
            gridResolution: options.gridResolution || 50,
            heatMapRadius: options.heatMapRadius || 500,
            routeSampleInterval: options.routeSampleInterval || 500,
            timeSliderStep: 15, // minutes
            animationInterval: 500 // ms between frames
        };
        
        // State
        this.state = {
            map: null,
            currentPosition: null,
            currentTimestamp: null,
            isPlaying: false,
            isLoading: false,
            gridLayer: null,
            buildingLayer: null,
            routeLayer: null,
            waypointLayer: null,
            deadZoneLayer: null,
            routePlan: null,
            selectedPoint: null,
            searchDebounceTimer: null,
            animationTimer: null,
            lastHeatMapRequest: null,
            lastScannedCenter: null
        };
        
        // API Client
        this.api = new APIClient({ baseURL: this.config.apiBaseURL });
        
        // Sky Plot
        this.skyPlot = null;
        
        // DOM Elements cache
        this.elements = {};
        
        // Bind methods
        this.handleResize = this.handleResize.bind(this);
        this.handleOnline = this.handleOnline.bind(this);
        this.handleOffline = this.handleOffline.bind(this);
    }
    
    // ============================================
    // INITIALIZATION
    // ============================================
    
    /**
     * Initialize the application
     * @returns {Promise<void>}
     */
    async init() {
        console.log('[LinkSpot] Initializing...');
        
        // Cache DOM elements
        this.cacheElements();
        
        // Initialize map
        this.initMap();
        
        // Initialize sky plot
        this.initSkyPlot();
        
        // Setup event listeners
        this.setupEventListeners();
        
        // Set initial time
        this.setCurrentTime(new Date());
        this.updateRoutePlanButtonState();
        
        // Check backend connectivity
        await this.checkBackendHealth();

        // Try to get user's location
        await this.centerOnGPS();
        
        // Load initial heat map
        if (this.state.currentPosition) {
            await this.loadHeatMap(
                this.state.currentPosition.lat,
                this.state.currentPosition.lon
            );
        }
        
        // Hide loading overlay
        this.setLoading(false);
        
        // Listen for Electron backend status updates
        if (window.electronAPI && window.electronAPI.onBackendStatus) {
            window.electronAPI.onBackendStatus((status) => {
                if (status.connected) {
                    this._hideBackendBanner();
                } else {
                    this._showBackendBanner();
                }
            });
        }

        console.log('[LinkSpot] Initialized successfully');
    }
    
    /**
     * Cache DOM element references
     * @private
     */
    cacheElements() {
        this.elements = {
            map: document.getElementById('map'),
            loadingOverlay: document.getElementById('loading-overlay'),
            offlineIndicator: document.getElementById('offline-indicator'),
            searchInput: document.getElementById('search-input'),
            searchBtn: document.getElementById('search-btn'),
            searchClear: document.getElementById('search-clear'),
            searchResults: document.getElementById('search-results'),
            gpsBtn: document.getElementById('gps-btn'),
            routePlanBtn: document.getElementById('route-plan-btn'),
            routeSummaryPanel: document.getElementById('route-summary-panel'),
            routeSummaryDistance: document.getElementById('route-summary-distance'),
            routeSummaryEta: document.getElementById('route-summary-eta'),
            routeSummaryDeadZone: document.getElementById('route-summary-deadzone'),
            routeSummaryWaypoints: document.getElementById('route-summary-waypoints'),
            routeSummaryClear: document.getElementById('route-summary-clear'),
            timeSlider: document.getElementById('time-slider'),
            currentTime: document.getElementById('current-time'),
            playBtn: document.getElementById('play-btn'),
            playIcon: document.getElementById('play-icon'),
            pauseIcon: document.getElementById('pause-icon'),
            legendToggle: document.getElementById('legend-toggle'),
            legendContainer: document.querySelector('.legend-container'),
            detailPanel: document.getElementById('detail-panel'),
            detailBackdrop: document.getElementById('detail-backdrop'),
            detailClose: document.getElementById('detail-close'),
            detailTitle: document.getElementById('detail-title'),
            detailCoords: document.getElementById('detail-coords'),
            detailStatus: document.getElementById('detail-status'),
            skyPlotCanvas: document.getElementById('sky-plot'),
            satelliteList: document.getElementById('satellite-list'),
            analysisStats: document.getElementById('analysis-stats'),
            toastContainer: document.getElementById('toast-container'),
            scanAreaBtn: document.getElementById('scan-area-btn')
        };
    }
    
    /**
     * Initialize Leaflet map with Canvas renderer
     * @private
     */
    initMap() {
        const { lat, lon, zoom } = this.config.initialPosition;
        
        // Create map with Canvas renderer for performance
        this.state.map = L.map('map', {
            renderer: L.canvas(),
            zoomControl: false,
            attributionControl: true
        }).setView([lat, lon], zoom);
        
        // Add zoom control to bottom right
        L.control.zoom({
            position: 'bottomright'
        }).addTo(this.state.map);
        
        // Add tile layer (dark themed)
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
            subdomains: 'abcd',
            maxZoom: 20
        }).addTo(this.state.map);
        
        // currentPosition is only set by GPS or search — never from defaults
        this.state.currentPosition = null;

        // Show "Scan this area" button when map pans away from last scan
        this.state.map.on('moveend', () => {
            if (!this.state.currentPosition) return;
            const center = this.state.map.getCenter();
            this.state.currentPosition = { lat: center.lat, lon: center.lng };
            this.updateRoutePlanButtonState();

            if (this.state.lastScannedCenter) {
                const dist = this._haversineDistance(
                    this.state.lastScannedCenter.lat, this.state.lastScannedCenter.lon,
                    center.lat, center.lng
                );
                if (dist > this.config.heatMapRadius * 0.25) {
                    this.elements.scanAreaBtn.classList.remove('hidden');
                } else {
                    this.elements.scanAreaBtn.classList.add('hidden');
                }
            }
        });
    }
    
    /**
     * Initialize sky plot visualization
     * @private
     */
    initSkyPlot() {
        if (this.elements.skyPlotCanvas) {
            this.skyPlot = new SkyPlot(this.elements.skyPlotCanvas, {
                satelliteColor: '#e94560',
                obstructedColor: '#6c757d',
                obstructionFill: 'rgba(108, 117, 125, 0.3)',
                gridColor: 'rgba(255, 255, 255, 0.2)',
                textColor: '#a0a0a0'
            });
        }
    }
    
    /**
     * Setup all event listeners
     * @private
     */
    setupEventListeners() {
        // Window events
        window.addEventListener('resize', this.handleResize);
        window.addEventListener('online', this.handleOnline);
        window.addEventListener('offline', this.handleOffline);
        
        // Search events
        this.elements.searchInput.addEventListener('input', (e) => {
            this.handleSearchInput(e.target.value);
            this.updateRoutePlanButtonState();
        });
        
        this.elements.searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                if (e.shiftKey) {
                    this.planRouteFromSearch();
                } else {
                    this.searchLocation(this.elements.searchInput.value);
                }
            }
        });
        
        this.elements.searchBtn.addEventListener('click', () => {
            this.searchLocation(this.elements.searchInput.value);
        });
        
        this.elements.searchClear.addEventListener('click', () => {
            this.clearSearch();
        });
        
        // GPS button
        this.elements.gpsBtn.addEventListener('click', () => {
            this.centerOnGPS();
        });

        // Route planning button
        this.elements.routePlanBtn.addEventListener('click', () => {
            this.planRouteFromSearch();
        });

        // Route summary clear button
        if (this.elements.routeSummaryClear) {
            this.elements.routeSummaryClear.addEventListener('click', () => {
                this.clearRoutePlan();
            });
        }

        // Scan area button
        this.elements.scanAreaBtn.addEventListener('click', () => {
            const center = this.state.map.getCenter();
            this.elements.scanAreaBtn.classList.add('hidden');
            this.loadHeatMap(center.lat, center.lng);
        });
        
        // Time slider
        this.elements.timeSlider.addEventListener('input', (e) => {
            this.onTimeSliderChange(parseInt(e.target.value, 10));
        });
        
        // Play button
        this.elements.playBtn.addEventListener('click', () => {
            this.toggleAnimation();
        });
        
        // Legend toggle
        this.elements.legendToggle.addEventListener('click', () => {
            this.elements.legendContainer.classList.toggle('collapsed');
            const isExpanded = !this.elements.legendContainer.classList.contains('collapsed');
            this.elements.legendToggle.setAttribute('aria-expanded', isExpanded);
        });
        
        // Detail panel
        this.elements.detailClose.addEventListener('click', () => {
            this.closeDetailPanel();
        });
        
        this.elements.detailBackdrop.addEventListener('click', () => {
            this.closeDetailPanel();
        });
        
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.closeDetailPanel();
                this.clearSearch();
            }
        });
        
        // Close search results on outside click
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.search-container')) {
                this.hideSearchResults();
            }
        });
    }
    
    // ============================================
    // MAP & HEAT MAP
    // ============================================
    
    /**
     * Load heat map data for a position
     * @param {number} lat - Latitude
     * @param {number} lon - Longitude
     * @returns {Promise<void>}
     */
    async loadHeatMap(lat, lon) {
        // Prevent duplicate requests for the same position
        const requestKey = `${lat.toFixed(4)},${lon.toFixed(4)}`;
        if (requestKey === this.state.lastHeatMapRequest) {
            return;
        }

        // Prevent concurrent requests
        if (this._heatmapLoading) {
            return;
        }

        this.state.lastHeatMapRequest = requestKey;
        this.state.lastScannedCenter = { lat, lon };
        this.elements.scanAreaBtn.classList.add('hidden');
        this._heatmapLoading = true;
        this.setLoading(true);

        try {
            const data = await this.api.getHeatMap(
                lat,
                lon,
                this.config.heatMapRadius,
                null, // timestamp omitted — server uses current time
                this.config.gridResolution
            );

            this.renderGridCells(data.grid);
            this.renderBuildings(data.buildings);

        } catch (error) {
            console.error('[LinkSpot] Failed to load heat map:', error);
            this.showToast('Failed to load heat map data', 'error');
            // Clear the request key so the user can retry
            this.state.lastHeatMapRequest = null;
        } finally {
            this._heatmapLoading = false;
            this.setLoading(false);
        }
    }
    
    /**
     * Render grid cells on the map
     * @param {Object} geojsonData - GeoJSON FeatureCollection of grid cells
     */
    renderGridCells(geojsonData) {
        // Remove existing grid layer
        if (this.state.gridLayer) {
            this.state.map.removeLayer(this.state.gridLayer);
        }
        
        // Create new grid layer
        this.state.gridLayer = L.geoJSON(geojsonData, {
            style: (feature) => {
                const status = feature.properties.status;
                const colors = {
                    clear: '#2E8B57',
                    marginal: '#D4A017',
                    dead: '#C0392B'
                };
                
                return {
                    fillColor: colors[status] || '#6c757d',
                    fillOpacity: 0.6,
                    color: 'rgba(255, 255, 255, 0.2)',
                    weight: 1
                };
            },
            onEachFeature: (feature, layer) => {
                // Add click handler for each cell
                layer.on('click', (e) => {
                    const center = feature.properties.center;
                    this.showPointDetails(center.lat, center.lon, feature.properties);
                });
                
                // Add hover tooltip
                const status = feature.properties.status;
                const count = feature.properties.visible_count;
                layer.bindTooltip(
                    `<strong>${status.charAt(0).toUpperCase() + status.slice(1)}</strong><br>` +
                    `${count} satellites visible`,
                    { direction: 'top', offset: [0, -10] }
                );
            }
        }).addTo(this.state.map);
    }
    
    /**
     * Render building footprints on the map
     * @param {Object} geojsonData - GeoJSON FeatureCollection of buildings
     */
    renderBuildings(geojsonData) {
        // Remove existing building layer
        if (this.state.buildingLayer) {
            this.state.map.removeLayer(this.state.buildingLayer);
        }
        
        if (!geojsonData || !geojsonData.features) return;
        
        // Create building layer
        this.state.buildingLayer = L.geoJSON(geojsonData, {
            style: {
                fillColor: '#6c757d',
                fillOpacity: 0.3,
                color: '#495057',
                weight: 1.5
            }
        }).addTo(this.state.map);
        
        // Ensure buildings are below grid cells
        if (this.state.gridLayer) {
            this.state.buildingLayer.bringToBack();
        }
    }

    /**
     * Update route-planning trigger visibility.
     * Requires current map position + destination text.
     */
    updateRoutePlanButtonState() {
        if (!this.elements.routePlanBtn) return;
        const hasOrigin = !!this.state.currentPosition;
        const hasDestinationText = this.elements.searchInput.value.trim().length > 1;
        this.elements.routePlanBtn.classList.toggle('hidden', !(hasOrigin && hasDestinationText));
    }

    /**
     * Remove all currently rendered route layers.
     */
    clearRoutePlan() {
        this.resetRouteSummaryPanel();
        if (!this.state.map) {
            this.state.routePlan = null;
            return;
        }

        if (this.state.routeLayer) {
            this.state.map.removeLayer(this.state.routeLayer);
            this.state.routeLayer = null;
        }
        if (this.state.waypointLayer) {
            this.state.map.removeLayer(this.state.waypointLayer);
            this.state.waypointLayer = null;
        }
        if (this.state.deadZoneLayer) {
            this.state.map.removeLayer(this.state.deadZoneLayer);
            this.state.deadZoneLayer = null;
        }
        this.state.routePlan = null;
    }

    /**
     * Reset and hide the route summary panel.
     */
    resetRouteSummaryPanel() {
        if (!this.elements.routeSummaryPanel) return;
        this.elements.routeSummaryDistance.textContent = '--';
        this.elements.routeSummaryEta.textContent = '--';
        this.elements.routeSummaryDeadZone.textContent = '--';
        this.elements.routeSummaryWaypoints.textContent = '--';
        this.elements.routeSummaryPanel.classList.add('hidden');
    }

    /**
     * Update route summary panel from route planning response.
     * @param {Object} routePlan
     */
    updateRouteSummaryPanel(routePlan) {
        if (!this.elements.routeSummaryPanel) return;
        const summary = routePlan?.mission_summary || {};
        const totalDistance = Number(summary.total_distance_m || 0);
        const durationSec = Number(summary.total_duration_s || 0);
        const deadZoneDistance = Number(summary.dead_zone_total_m || 0);
        const waypointCount = Number(summary.num_waypoints || 0);

        const distanceText = totalDistance >= 1000
            ? `${(totalDistance / 1000).toFixed(1)} km`
            : `${Math.round(totalDistance)} m`;
        const etaText = this.formatDuration(durationSec);
        const deadZonePct = totalDistance > 0
            ? ((deadZoneDistance / totalDistance) * 100).toFixed(1)
            : '0.0';

        this.elements.routeSummaryDistance.textContent = distanceText;
        this.elements.routeSummaryEta.textContent = etaText;
        this.elements.routeSummaryDeadZone.textContent = `${deadZonePct}%`;
        this.elements.routeSummaryWaypoints.textContent = `${waypointCount}`;
        this.elements.routeSummaryPanel.classList.remove('hidden');
    }

    /**
     * Format duration seconds to compact h/m form.
     * @param {number} seconds
     * @returns {string}
     */
    formatDuration(seconds) {
        if (!Number.isFinite(seconds) || seconds <= 0) return '--';
        const totalMinutes = Math.round(seconds / 60);
        const hours = Math.floor(totalMinutes / 60);
        const minutes = totalMinutes % 60;
        if (hours > 0 && minutes > 0) return `${hours}h ${minutes}m`;
        if (hours > 0) return `${hours}h`;
        return `${minutes}m`;
    }

    /**
     * Plan a route from current position to the search destination.
     */
    async planRouteFromSearch() {
        const destinationText = this.elements.searchInput.value.trim();
        if (!destinationText) {
            this.showToast('Enter a destination in search to plan a route', 'warning');
            return;
        }

        const origin = this.state.currentPosition
            || (this.state.map ? this.state.map.getCenter() : null);
        if (!origin) {
            this.showToast('Set your origin first (GPS or map position)', 'warning');
            return;
        }

        // Support "lat,lon" destination shortcuts in addition to addresses.
        let destination = { address: destinationText };
        const coordMatch = destinationText.match(/^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/);
        if (coordMatch) {
            destination = {
                lat: parseFloat(coordMatch[1]),
                lon: parseFloat(coordMatch[2])
            };
        }

        await this.loadRoutePlan(
            { lat: origin.lat, lon: origin.lon },
            destination
        );
    }

    /**
     * Fetch and render route-planning analysis from backend.
     * @param {{lat:number, lon:number}|{address:string}} origin
     * @param {{lat:number, lon:number}|{address:string}} destination
     */
    async loadRoutePlan(origin, destination) {
        if (this._routeLoading) return;
        this._routeLoading = true;
        this.setLoading(true);
        if (this.elements.routePlanBtn) {
            this.elements.routePlanBtn.classList.add('loading');
        }

        try {
            const routePlan = await this.api.planRoute(
                origin,
                destination,
                this.config.routeSampleInterval,
                this.state.currentTimestamp
            );
            this.state.routePlan = routePlan;
            this.renderRoutePlan(routePlan);
            this.updateRouteSummaryPanel(routePlan);
        } catch (error) {
            console.error('[LinkSpot] Route planning failed:', error);
            this.showToast('Failed to plan route', 'error');
        } finally {
            this._routeLoading = false;
            this.setLoading(false);
            if (this.elements.routePlanBtn) {
                this.elements.routePlanBtn.classList.remove('loading');
            }
        }
    }

    /**
     * Render route segments, waypoints, and dead zones.
     * @param {Object} routePlan
     */
    renderRoutePlan(routePlan) {
        this.clearRoutePlan();
        if (!routePlan || !this.state.map) return;

        const routeGeoJson = routePlan.route_geojson;
        if (routeGeoJson && Array.isArray(routeGeoJson.features)) {
            this.state.routeLayer = L.geoJSON(routeGeoJson, {
                style: (feature) => this.getRouteSegmentStyle(feature?.properties?.signal),
                onEachFeature: (feature, layer) => {
                    const props = feature.properties || {};
                    const signal = props.signal || 'dead';
                    const visible = props.visible_satellites ?? 0;
                    const total = props.total_satellites ?? 0;
                    layer.bindTooltip(
                        `<strong>${signal.toUpperCase()}</strong><br>${visible}/${total} satellites`,
                        { direction: 'top', offset: [0, -6] }
                    );
                }
            }).addTo(this.state.map);
        }

        const waypoints = Array.isArray(routePlan.waypoints) ? routePlan.waypoints : [];
        this.state.waypointLayer = L.layerGroup();
        waypoints.forEach((wp) => {
            const color = this.getZoneColor(wp.zone);
            const marker = L.circleMarker([wp.lat, wp.lon], {
                radius: 7,
                color: '#ffffff',
                weight: 2,
                fillColor: color,
                fillOpacity: 0.95
            });
            const etaMin = wp.eta_seconds ? Math.round(wp.eta_seconds / 60) : 0;
            marker.bindPopup(
                `<strong>${this.escapeHtml(wp.name || wp.id)}</strong><br>` +
                `${this.escapeHtml((wp.type || 'stop').replace('_', ' '))}<br>` +
                `Coverage: ${Math.round(wp.coverage_pct || 0)}%<br>` +
                `Sats: ${wp.visible_satellites || 0}/${wp.total_satellites || 0}<br>` +
                `ETA: ${etaMin} min`
            );
            marker.addTo(this.state.waypointLayer);
        });
        this.state.waypointLayer.addTo(this.state.map);

        const deadZones = Array.isArray(routePlan.dead_zones) ? routePlan.dead_zones : [];
        this.state.deadZoneLayer = L.layerGroup();
        deadZones.forEach((dz) => {
            const deadLine = L.polyline(
                [[dz.start_lat, dz.start_lon], [dz.end_lat, dz.end_lon]],
                {
                    color: '#C0392B',
                    weight: 6,
                    opacity: 0.9,
                    dashArray: '8 8'
                }
            );
            deadLine.bindTooltip(
                `<strong>Dead Zone</strong><br>Length: ${(dz.length_m / 1000).toFixed(2)} km`
            );
            deadLine.addTo(this.state.deadZoneLayer);
        });
        this.state.deadZoneLayer.addTo(this.state.map);

        if (this.state.routeLayer && this.state.routeLayer.getBounds().isValid()) {
            this.state.map.fitBounds(this.state.routeLayer.getBounds(), {
                padding: [36, 36],
                maxZoom: 15
            });
        }

        if (this.state.routeLayer) {
            this.state.routeLayer.bringToFront();
        }
        if (this.state.deadZoneLayer) {
            this.state.deadZoneLayer.bringToFront();
        }
        if (this.state.waypointLayer) {
            this.state.waypointLayer.bringToFront();
        }
    }

    /**
     * Segment styling for route signal classes.
     * @param {string} signal
     * @returns {Object} Leaflet polyline style
     */
    getRouteSegmentStyle(signal) {
        const colors = {
            clear: '#2E8B57',
            marginal: '#D4A017',
            dead: '#C0392B'
        };
        return {
            color: colors[signal] || '#6c757d',
            weight: 5,
            opacity: 0.88,
            lineCap: 'round',
            lineJoin: 'round'
        };
    }

    /**
     * Color map for waypoint zone values.
     * @param {string} zone
     * @returns {string}
     */
    getZoneColor(zone) {
        const value = (zone || '').toLowerCase();
        if (value === 'excellent' || value === 'good') return '#2E8B57';
        if (value === 'fair') return '#D4A017';
        return '#C0392B';
    }
    
    // ============================================
    // TIME SLIDER
    // ============================================
    
    /**
     * Set the current analysis time
     * @param {Date} date - The date/time to set
     */
    setCurrentTime(date) {
        this.state.currentTimestamp = date.toISOString();
        
        // Update time display
        const hours = date.getHours().toString().padStart(2, '0');
        const minutes = date.getMinutes().toString().padStart(2, '0');
        this.elements.currentTime.textContent = `${hours}:${minutes}`;
        
        // Update slider position
        const totalMinutes = date.getHours() * 60 + date.getMinutes();
        const sliderValue = Math.floor(totalMinutes / this.config.timeSliderStep);
        this.elements.timeSlider.value = sliderValue;
        this.elements.timeSlider.setAttribute('aria-valuenow', sliderValue);
    }
    
    /**
     * Handle time slider change
     * @param {number} sliderValue - Slider value (0-95 for 15-min increments)
     */
    onTimeSliderChange(sliderValue) {
        // Convert slider value to time
        const totalMinutes = sliderValue * this.config.timeSliderStep;
        const hours = Math.floor(totalMinutes / 60);
        const minutes = totalMinutes % 60;

        // Create new date with selected time
        const now = new Date();
        const newDate = new Date(
            now.getFullYear(),
            now.getMonth(),
            now.getDate(),
            hours,
            minutes
        );

        this.setCurrentTime(newDate);

        // Heatmap only refreshes when position changes, not on time change.
        // Satellite geometry shifts negligibly over hours for a fixed location.
    }
    
    /**
     * Toggle time animation
     */
    toggleAnimation() {
        this.state.isPlaying = !this.state.isPlaying;
        
        // Update play button icon
        this.elements.playIcon.classList.toggle('hidden', this.state.isPlaying);
        this.elements.pauseIcon.classList.toggle('hidden', !this.state.isPlaying);
        
        if (this.state.isPlaying) {
            this.startAnimation();
        } else {
            this.stopAnimation();
        }
    }
    
    /**
     * Start time animation
     * @private
     */
    startAnimation() {
        this.state.animationTimer = setInterval(() => {
            let currentValue = parseInt(this.elements.timeSlider.value, 10);
            currentValue = (currentValue + 1) % 96; // Wrap around at 24 hours
            this.elements.timeSlider.value = currentValue;
            this.onTimeSliderChange(currentValue);
        }, this.config.animationInterval);
    }
    
    /**
     * Stop time animation
     * @private
     */
    stopAnimation() {
        if (this.state.animationTimer) {
            clearInterval(this.state.animationTimer);
            this.state.animationTimer = null;
        }
    }
    
    // ============================================
    // SEARCH
    // ============================================
    
    /**
     * Handle search input with debouncing
     * @private
     * @param {string} query - Search query
     */
    handleSearchInput(query) {
        // Show/hide clear button
        this.elements.searchClear.classList.toggle('hidden', query.length === 0);
        
        // Debounce search
        clearTimeout(this.state.searchDebounceTimer);
        
        if (query.length < 3) {
            this.hideSearchResults();
            return;
        }
        
        this.state.searchDebounceTimer = setTimeout(() => {
            this.fetchSearchSuggestions(query);
        }, 300);
    }
    
    /**
     * Fetch search suggestions from Nominatim
     * @private
     * @param {string} query - Search query
     */
    async fetchSearchSuggestions(query) {
        try {
            const response = await fetch(
                `https://nominatim.openstreetmap.org/search?` +
                `format=json&q=${encodeURIComponent(query)}&limit=5`,
                { headers: { 'Accept-Language': 'en' } }
            );
            
            const results = await response.json();
            this.displaySearchResults(results);
            
        } catch (error) {
            console.error('[LinkSpot] Search failed:', error);
        }
    }
    
    /**
     * Display search results dropdown
     * @private
     * @param {Array} results - Search results
     */
    displaySearchResults(results) {
        if (!results || results.length === 0) {
            this.hideSearchResults();
            return;
        }
        
        const html = results.map((result, index) => `
            <div 
                class="search-result-item" 
                role="option"
                data-index="${index}"
                data-lat="${result.lat}"
                data-lon="${result.lon}"
            >
                <div class="search-result-name">${this.escapeHtml(result.display_name.split(',')[0])}</div>
                <div class="search-result-address">${this.escapeHtml(result.display_name)}</div>
            </div>
        `).join('');
        
        this.elements.searchResults.innerHTML = html;
        this.elements.searchResults.classList.add('visible');
        
        // Add click handlers
        this.elements.searchResults.querySelectorAll('.search-result-item').forEach(item => {
            item.addEventListener('click', () => {
                const lat = parseFloat(item.dataset.lat);
                const lon = parseFloat(item.dataset.lon);
                const name = item.querySelector('.search-result-name').textContent;
                
                this.selectSearchResult(lat, lon, name);
            });
        });
    }
    
    /**
     * Select a search result
     * @private
     * @param {number} lat - Latitude
     * @param {number} lon - Longitude
     * @param {string} name - Location name
     */
    selectSearchResult(lat, lon, name) {
        // Update search input
        this.elements.searchInput.value = name;
        this.hideSearchResults();
        
        // Center map
        this.state.map.setView([lat, lon], 17);
        this.state.currentPosition = { lat, lon };
        this.updateRoutePlanButtonState();
        
        // Load heat map
        this.loadHeatMap(lat, lon);
        
        this.showToast(`Location: ${name}`, 'success');
    }
    
    /**
     * Hide search results dropdown
     * @private
     */
    hideSearchResults() {
        this.elements.searchResults.classList.remove('visible');
    }
    
    /**
     * Clear search input and results
     */
    clearSearch() {
        this.elements.searchInput.value = '';
        this.elements.searchClear.classList.add('hidden');
        this.hideSearchResults();
        this.updateRoutePlanButtonState();
        this.elements.searchInput.focus();
    }
    
    /**
     * Search for a location
     * @param {string} query - Search query
     */
    async searchLocation(query) {
        if (!query.trim()) return;
        
        this.setLoading(true);
        
        try {
            const response = await fetch(
                `https://nominatim.openstreetmap.org/search?` +
                `format=json&q=${encodeURIComponent(query)}&limit=1`,
                { headers: { 'Accept-Language': 'en' } }
            );
            
            const results = await response.json();
            
            if (results && results.length > 0) {
                const result = results[0];
                this.selectSearchResult(
                    parseFloat(result.lat),
                    parseFloat(result.lon),
                    result.display_name.split(',')[0]
                );
            } else {
                this.showToast('Location not found', 'error');
            }
            
        } catch (error) {
            console.error('[LinkSpot] Search failed:', error);
            this.showToast('Search failed. Please try again.', 'error');
        } finally {
            this.setLoading(false);
        }
    }
    
    // ============================================
    // GPS
    // ============================================
    
    /**
     * Center map on user's GPS location
     * @returns {Promise<void>}
     */
    async centerOnGPS() {
        if (!navigator.geolocation) {
            this.showToast('Geolocation is not supported', 'error');
            return;
        }
        
        this.elements.gpsBtn.classList.add('loading');
        
        try {
            const position = await new Promise((resolve, reject) => {
                navigator.geolocation.getCurrentPosition(resolve, reject, {
                    enableHighAccuracy: true,
                    timeout: 10000,
                    maximumAge: 60000
                });
            });
            
            const { latitude, longitude } = position.coords;
            
            // Center map
            this.state.map.setView([latitude, longitude], 17);
            this.state.currentPosition = { lat: latitude, lon: longitude };
            this.updateRoutePlanButtonState();
            
            // Add marker
            L.marker([latitude, longitude])
                .addTo(this.state.map)
                .bindPopup('Your Location')
                .openPopup();
            
            // Load heat map
            await this.loadHeatMap(latitude, longitude);
            
            this.elements.gpsBtn.classList.add('active');
            this.showToast('Location found', 'success');
            
        } catch (error) {
            console.error('[LinkSpot] GPS error:', error);
            
            let message = 'Unable to get location';
            if (error.code === 1) message = 'Location permission denied';
            if (error.code === 2) message = 'Location unavailable';
            if (error.code === 3) message = 'Location request timeout';
            
            this.showToast(message, 'error');
        } finally {
            this.elements.gpsBtn.classList.remove('loading');
        }
    }
    
    // ============================================
    // DETAIL PANEL
    // ============================================
    
    /**
     * Show point details panel
     * @param {number} lat - Latitude
     * @param {number} lon - Longitude
     * @param {Object} data - Point data
     */
    async showPointDetails(lat, lon, data = {}) {
        this.state.selectedPoint = { lat, lon };
        
        // Update panel content
        this.elements.detailTitle.textContent = 'Location Details';
        this.elements.detailCoords.textContent = `${lat.toFixed(6)}, ${lon.toFixed(6)}`;
        
        // Set status
        const status = data.status || 'unknown';
        const statusText = {
            clear: '✓ Clear - Good satellite visibility',
            marginal: '⚠ Marginal - Limited satellite visibility',
            dead: '✗ Dead Zone - Poor satellite visibility',
            unknown: '? Unknown - Analysis unavailable'
        };
        
        this.elements.detailStatus.className = `detail-status ${status}`;
        this.elements.detailStatus.innerHTML = `
            <span class="status-icon">${statusText[status]?.split(' ')[0] || '?'}</span>
            <span>${statusText[status]?.substring(2) || 'Unknown'}</span>
        `;
        
        // Show panel
        this.elements.detailPanel.classList.add('open');
        this.elements.detailPanel.setAttribute('aria-hidden', 'false');
        this.elements.detailBackdrop.classList.add('visible');
        document.body.style.overflow = 'hidden';
        
        // Fetch detailed analysis
        try {
            const analysis = await this.api.analyzePosition(lat, lon, this.state.currentTimestamp);
            this.updateDetailPanel(analysis);
        } catch (error) {
            console.error('[LinkSpot] Analysis failed:', error);
            this.showToast('Failed to load analysis', 'error');
        }
    }
    
    /**
     * Update detail panel with analysis data
     * @private
     * @param {Object} analysis - Analysis result
     */
    updateDetailPanel(analysis) {
        // Update sky plot
        if (this.skyPlot && analysis.satellites) {
            this.skyPlot.setData(
                analysis.satellites,
                analysis.obstructions || []
            );
        }
        
        // Update satellite list
        if (analysis.satellites) {
            const visibleSats = analysis.satellites.filter(s => s.visible && !s.obstructed);
            
            this.elements.satelliteList.innerHTML = visibleSats.map(sat => `
                <li class="satellite-item">
                    <span class="satellite-name">${sat.name || sat.id}</span>
                    <span class="satellite-info">
                        <span class="satellite-elevation">${Math.round(sat.elevation)}°</span>
                        <span class="satellite-snr ${this.getSNRClass(sat.snr)}">${sat.snr != null ? sat.snr + ' dB' : '--'}</span>
                    </span>
                </li>
            `).join('');
        }
        
        // Update analysis stats
        if (analysis.visibility) {
            this.elements.analysisStats.innerHTML = `
                <div class="stat-item">
                    <div class="stat-value">${analysis.visibility.visible_satellites}</div>
                    <div class="stat-label">Visible</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">${analysis.visibility.obstructed_satellites}</div>
                    <div class="stat-label">Obstructed</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">${analysis.visibility.total_satellites}</div>
                    <div class="stat-label">Total</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">${Math.round((analysis.visibility.visible_satellites / analysis.visibility.total_satellites) * 100)}%</div>
                    <div class="stat-label">Coverage</div>
                </div>
            `;
        }
    }
    
    /**
     * Get SNR quality class
     * @private
     * @param {number} snr - Signal-to-noise ratio
     * @returns {string} CSS class name
     */
    getSNRClass(snr) {
        if (snr == null) return 'unknown';
        if (snr >= 40) return 'good';
        if (snr >= 30) return 'moderate';
        return 'poor';
    }
    
    /**
     * Close detail panel
     */
    closeDetailPanel() {
        this.elements.detailPanel.classList.remove('open');
        this.elements.detailPanel.setAttribute('aria-hidden', 'true');
        this.elements.detailBackdrop.classList.remove('visible');
        document.body.style.overflow = '';
        this.state.selectedPoint = null;
    }
    
    // ============================================
    // LEGEND
    // ============================================
    
    /**
     * Update legend based on current view
     */
    updateLegend() {
        // Legend updates can be implemented based on view context
        // For now, the legend is static
    }
    
    // ============================================
    // UI HELPERS
    // ============================================
    
    /**
     * Set loading state
     * @param {boolean} isLoading - Whether app is loading
     */
    setLoading(isLoading) {
        this.state.isLoading = isLoading;
        this.elements.loadingOverlay.setAttribute('aria-hidden', !isLoading);
    }
    
    /**
     * Show toast notification
     * @param {string} message - Message to display
     * @param {string} type - Toast type (success, error, warning, info)
     * @param {number} duration - Display duration in ms
     */
    showToast(message, type = 'info', duration = 3000) {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;
        
        this.elements.toastContainer.appendChild(toast);
        
        setTimeout(() => {
            toast.remove();
        }, duration);
    }
    
    /**
     * Escape HTML special characters
     * @private
     * @param {string} text - Text to escape
     * @returns {string} Escaped text
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    // ============================================
    // EVENT HANDLERS
    // ============================================
    
    /**
     * Handle window resize
     * @private
     */
    handleResize() {
        if (this.state.map) {
            this.state.map.invalidateSize();
        }
        
        if (this.skyPlot) {
            const container = this.elements.skyPlotCanvas.parentElement;
            const size = Math.min(container.clientWidth, 280);
            this.skyPlot.resize(size, size);
        }
    }
    
    /**
     * Handle online event
     * @private
     */
    handleOnline() {
        this.elements.offlineIndicator.classList.remove('visible');
        this.showToast('Back online', 'success');
    }
    
    /**
     * Handle offline event
     * @private
     */
    handleOffline() {
        this.elements.offlineIndicator.classList.add('visible');
        this.showToast('You are offline', 'warning');
    }
    
    /**
     * Check backend connectivity and show banner if unavailable
     * @private
     */
    async checkBackendHealth() {
        try {
            await this.api.healthCheck();
            this._hideBackendBanner();
        } catch (error) {
            this._showBackendBanner();
        }
    }

    /** @private */
    _showBackendBanner() {
        let banner = document.getElementById('backend-banner');
        if (banner) return;
        banner = document.createElement('div');
        banner.id = 'backend-banner';
        banner.className = 'backend-banner';

        const isElectron = window.electronAPI && window.electronAPI.isElectron;
        const message = isElectron
            ? 'Backend unavailable. Start the backend with <code>make up</code> or update the URL in Preferences.'
            : 'Backend unavailable. Ensure the server is running.';

        banner.innerHTML =
            '<span class="backend-banner-icon">&#9888;</span>' +
            '<span class="backend-banner-text">' + message + '</span>' +
            '<button class="backend-banner-retry" id="backend-retry-btn">Retry</button>' +
            '<button class="backend-banner-close" id="backend-close-btn" aria-label="Dismiss">&times;</button>';
        document.body.prepend(banner);

        document.getElementById('backend-retry-btn').addEventListener('click', () => this.checkBackendHealth());
        document.getElementById('backend-close-btn').addEventListener('click', () => banner.remove());
    }

    /** @private */
    _hideBackendBanner() {
        const banner = document.getElementById('backend-banner');
        if (banner) banner.remove();
    }

    /**
     * Approximate distance between two points in meters (haversine)
     * @private
     */
    _haversineDistance(lat1, lon1, lat2, lon2) {
        const R = 6371000;
        const dLat = (lat2 - lat1) * Math.PI / 180;
        const dLon = (lon2 - lon1) * Math.PI / 180;
        const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
                  Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
                  Math.sin(dLon/2) * Math.sin(dLon/2);
        return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
    }

    // ============================================
    // CLEANUP
    // ============================================
    
    /**
     * Destroy the application and clean up
     */
    destroy() {
        // Stop animation
        this.stopAnimation();

        // Remove route overlays
        this.clearRoutePlan();
        
        // Remove event listeners
        window.removeEventListener('resize', this.handleResize);
        window.removeEventListener('online', this.handleOnline);
        window.removeEventListener('offline', this.handleOffline);
        
        // Destroy map
        if (this.state.map) {
            this.state.map.remove();
            this.state.map = null;
        }
        
        // Destroy sky plot
        if (this.skyPlot) {
            this.skyPlot.destroy();
            this.skyPlot = null;
        }
        
        console.log('[LinkSpot] Destroyed');
    }
}

// ============================================
// APPLICATION STARTUP
// ============================================

/**
 * Initialize LinkSpot when DOM is ready
 */
document.addEventListener('DOMContentLoaded', () => {
    // Check for URL parameters
    const urlParams = new URLSearchParams(window.location.search);
    const action = urlParams.get('action');
    
    // Create and initialize app
    window.linkSpotApp = new LinkSpotApp({
        apiBaseURL: '/api/v1',
        initialPosition: urlParams.get('lat') && urlParams.get('lon') ? {
            lat: parseFloat(urlParams.get('lat')),
            lon: parseFloat(urlParams.get('lon')),
            zoom: parseInt(urlParams.get('zoom'), 10) || 16
        } : undefined
    });
    
    window.linkSpotApp.init().then(() => {
        // Handle shortcut actions
        if (action === 'locate') {
            window.linkSpotApp.centerOnGPS();
        } else if (action === 'search') {
            document.getElementById('search-input').focus();
        }
    });
});

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { LinkSpotApp };
}

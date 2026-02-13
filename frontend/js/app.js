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
            initialPosition: options.initialPosition || { lat: 40.7128, lon: -74.0060, zoom: 16 },
            gridResolution: options.gridResolution || 50,
            heatMapRadius: options.heatMapRadius || 500,
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
            selectedPoint: null,
            searchDebounceTimer: null,
            animationTimer: null,
            lastHeatMapRequest: null
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
            toastContainer: document.getElementById('toast-container')
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
        
        // Store initial position
        this.state.currentPosition = { lat, lon };
        
        // Setup map event handlers
        this.state.map.on('moveend', () => {
            const center = this.state.map.getCenter();
            this.state.currentPosition = { lat: center.lat, lon: center.lng };
        });
        
        // Debounced heat map load on map move
        let moveTimeout;
        this.state.map.on('moveend', () => {
            clearTimeout(moveTimeout);
            moveTimeout = setTimeout(() => {
                const center = this.state.map.getCenter();
                this.loadHeatMap(center.lat, center.lng);
            }, 500);
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
        });
        
        this.elements.searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                this.searchLocation(this.elements.searchInput.value);
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
        // Prevent duplicate requests
        const requestKey = `${lat.toFixed(4)},${lon.toFixed(4)},${this.state.currentTimestamp}`;
        if (requestKey === this.state.lastHeatMapRequest) {
            return;
        }
        this.state.lastHeatMapRequest = requestKey;
        
        this.setLoading(true);
        
        try {
            const data = await this.api.getHeatMap(
                lat,
                lon,
                this.config.heatMapRadius,
                this.state.currentTimestamp,
                this.config.gridResolution
            );
            
            this.renderGridCells(data.grid);
            this.renderBuildings(data.buildings);
            
        } catch (error) {
            console.error('[LinkSpot] Failed to load heat map:', error);
            this.showToast('Failed to load heat map data', 'error');
        } finally {
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
        
        // Reload heat map with new time
        if (this.state.currentPosition) {
            this.loadHeatMap(
                this.state.currentPosition.lat,
                this.state.currentPosition.lon
            );
        }
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
                        <span class="satellite-snr ${this.getSNRClass(sat.snr)}">${sat.snr} dB</span>
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
    
    // ============================================
    // CLEANUP
    // ============================================
    
    /**
     * Destroy the application and clean up
     */
    destroy() {
        // Stop animation
        this.stopAnimation();
        
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
        initialPosition: {
            lat: parseFloat(urlParams.get('lat')) || 40.7128,
            lon: parseFloat(urlParams.get('lon')) || -74.0060,
            zoom: parseInt(urlParams.get('zoom'), 10) || 16
        }
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

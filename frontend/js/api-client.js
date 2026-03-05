/**
 * LinkSpot API Client
 * Handles all communication with the backend API
 * Includes retry logic, error handling, and offline support
 * @version 1.0.0
 */

/**
 * API Client class for LinkSpot backend communication
 */
class APIClient {
    /**
     * Create an API client instance
     * @param {Object} options - Configuration options
     * @param {string} options.baseURL - Base URL for API requests
     * @param {number} options.timeout - Request timeout in milliseconds
     * @param {number} options.maxRetries - Maximum number of retry attempts
     * @param {number} options.retryDelay - Delay between retries in milliseconds
     */
    constructor(options = {}) {
        this.baseURL = options.baseURL || '/api/v1';
        this.timeout = options.timeout || 30000;
        this.maxRetries = options.maxRetries || 2;
        this.retryDelay = options.retryDelay || 2000;
        // TODO: Add request interceptors/middleware hooks for auth refresh and observability.
        
        // Request queue for offline support
        this.queueStorageKey = 'linkspot.api.requestQueue.v1';
        this.requestQueue = this.loadPersistedQueue();
        this.isOnline = navigator.onLine;
        
        // Bind online/offline events
        window.addEventListener('online', () => {
            this.isOnline = true;
            this.processQueue();
        });
        window.addEventListener('offline', () => {
            this.isOnline = false;
        });

        if (this.isOnline && this.requestQueue.length > 0) {
            this.processQueue();
        }
    }
    
    /**
     * Make an HTTP request with retry logic
     * @private
     * @param {string} endpoint - API endpoint
     * @param {Object} options - Fetch options
     * @param {number} attempt - Current attempt number
     * @returns {Promise<Object>} Response data
     */
    async request(endpoint, options = {}, attempt = 1) {
        const {
            _timeoutMs,
            _maxRetries,
            signal: externalSignal,
            ...fetchOptions
        } = options;
        const url = `${this.baseURL}${endpoint}`;
        const controller = new AbortController();
        const timeoutMs = Number.isFinite(_timeoutMs) ? _timeoutMs : this.timeout;
        const maxRetries = Number.isFinite(_maxRetries) ? _maxRetries : this.maxRetries;
        const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
        const onExternalAbort = () => controller.abort();
        if (externalSignal && typeof externalSignal.addEventListener === 'function') {
            if (externalSignal.aborted) {
                controller.abort();
            } else {
                externalSignal.addEventListener('abort', onExternalAbort, { once: true });
            }
        }
        
        const method = String(fetchOptions.method || 'GET').toUpperCase();
        if (!this.isOnline && method !== 'GET') {
            return this.queueRequest(endpoint, { ...fetchOptions, method });
        }

        try {
            const response = await fetch(url, {
                ...fetchOptions,
                signal: controller.signal,
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    ...fetchOptions.headers
                }
            });
            
            clearTimeout(timeoutId);
            
            // Handle HTTP errors
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new APIError(
                    errorData.message || `HTTP ${response.status}: ${response.statusText}`,
                    response.status,
                    errorData
                );
            }
            if (response.status === 204) {
                return {};
            }
            
            // Parse JSON response
            const data = await response.json().catch(() => ({}));
            
            // Check for cached response from service worker
            const isCached = response.headers.get('X-SW-Cached') === 'true';
            if (isCached) {
                data._cached = true;
            }
            
            return data;
            
        } catch (error) {
            clearTimeout(timeoutId);
            if (externalSignal && typeof externalSignal.removeEventListener === 'function') {
                externalSignal.removeEventListener('abort', onExternalAbort);
            }
            
            // Handle abort/timeout
            if (error.name === 'AbortError') {
                if (externalSignal?.aborted) {
                    throw new APIError('Request cancelled', 499, { endpoint });
                }
                throw new APIError('Request timeout', 408, {
                    endpoint,
                    timeout_ms: timeoutMs
                });
            }
            
            // Handle network errors with retry
            if (attempt < maxRetries && this.shouldRetry(error)) {
                const jitter = Math.random() * 250;
                await this.delay((this.retryDelay * attempt) + jitter);
                return this.request(endpoint, options, attempt + 1);
            }
            
            throw error;
        } finally {
            clearTimeout(timeoutId);
            if (externalSignal && typeof externalSignal.removeEventListener === 'function') {
                externalSignal.removeEventListener('abort', onExternalAbort);
            }
        }
    }
    
    /**
     * Determine if a request should be retried
     * @private
     * @param {Error} error - The error that occurred
     * @returns {boolean} Whether to retry
     */
    shouldRetry(error) {
        // Retry on network errors and 5xx status codes, but not 429
        if (error instanceof APIError) {
            return (error.status >= 500 || error.status === 408) && error.status !== 429;
        }
        return true; // Network errors
    }
    
    /**
     * Delay for a specified duration
     * @private
     * @param {number} ms - Milliseconds to delay
     * @returns {Promise<void>}
     */
    delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
    
    /**
     * Process queued requests when back online
     * @private
     */
    async processQueue() {
        while (this.requestQueue.length > 0 && this.isOnline) {
            const { endpoint, options, resolve, reject } = this.requestQueue.shift();
            this.persistQueue();
            try {
                const result = await this.request(endpoint, options);
                if (typeof resolve === 'function') resolve(result);
            } catch (error) {
                if (typeof reject === 'function') reject(error);
            }
            await this.delay(200);
        }
    }
    
    /**
     * Queue a request for later when offline
     * @private
     * @param {string} endpoint - API endpoint
     * @param {Object} options - Request options
     * @returns {Promise<Object>} Queued request promise
     */
    queueRequest(endpoint, options) {
        const queueItem = {
            id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            endpoint,
            options: {
                ...options,
                signal: undefined
            },
            queuedAt: Date.now()
        };
        return new Promise((resolve, reject) => {
            this.requestQueue.push({ ...queueItem, resolve, reject });
            this.persistQueue();
            resolve({
                queued: true,
                queue_id: queueItem.id
            });
        });
    }

    loadPersistedQueue() {
        try {
            const raw = localStorage.getItem(this.queueStorageKey);
            if (!raw) return [];
            const parsed = JSON.parse(raw);
            if (!Array.isArray(parsed)) return [];
            return parsed.map((item) => ({
                endpoint: item.endpoint,
                options: item.options || {}
            }));
        } catch {
            return [];
        }
    }

    persistQueue() {
        try {
            const serializable = this.requestQueue.map((item) => ({
                endpoint: item.endpoint,
                options: item.options
            }));
            localStorage.setItem(this.queueStorageKey, JSON.stringify(serializable));
        } catch (_error) {
            // Ignore storage failures in restricted/private environments.
        }
    }

    /**
     * Normalize a route location payload.
     * Accepts either { lat, lon } or { address }.
     * @private
     * @param {Object} location - Route location object
     * @param {string} label - Field name for error messages
     * @returns {Object} Normalized location payload
     */
    normalizeRouteLocation(location, label) {
        if (!location || typeof location !== 'object') {
            throw new TypeError(`${label} must be an object`);
        }

        const address = typeof location.address === 'string'
            ? location.address.trim()
            : '';
        if (address.length > 0) {
            return { address };
        }

        const hasLat = location.lat !== undefined && location.lat !== null;
        const hasLon = location.lon !== undefined && location.lon !== null;

        if (hasLat !== hasLon) {
            throw new TypeError(`${label} must include both lat and lon`);
        }

        if (hasLat && hasLon) {
            const lat = Number.parseFloat(location.lat);
            const lon = Number.parseFloat(location.lon);
            if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
                throw new TypeError(`${label} lat/lon must be valid numbers`);
            }
            return { lat, lon };
        }

        throw new TypeError(`${label} must include either address or lat/lon`);
    }
    
    // ============================================
    // API ENDPOINTS
    // ============================================
    
    /**
     * Analyze a single position for satellite visibility
     * @param {number} lat - Latitude
     * @param {number} lon - Longitude
     * @param {string|number} [timestamp] - ISO timestamp or Unix timestamp
     * @returns {Promise<Object>} Analysis result
     * 
     * Response format:
     * {
     *   location: { lat, lon, elevation },
     *   timestamp: string,
     *   visibility: {
     *     status: 'clear' | 'marginal' | 'dead',
     *     visible_satellites: number,
     *     obstructed_satellites: number,
     *     total_satellites: number
     *   },
     *   satellites: [{
     *     id: string,
     *     name: string,
     *     azimuth: number,
     *     elevation: number,
     *     snr: number,
     *     visible: boolean
     *   }],
     *   obstructions: [{
     *     azimuth: number,
     *     elevation: number,
     *     distance: number
     *   }]
     * }
     */
    async analyzePosition(lat, lon, timestamp = null) {
        const body = {
            lat: parseFloat(lat),
            lon: parseFloat(lon)
        };
        
        if (timestamp) {
            body.timestamp = timestamp;
        }
        
        return this.request('/analyze', {
            method: 'POST',
            body: JSON.stringify(body)
        });
    }
    
    /**
     * Get heat map data for a grid around a position
     * @param {number} lat - Center latitude
     * @param {number} lon - Center longitude
     * @param {number} [radius=500] - Radius in meters
     * @param {string|number} [timestamp] - ISO timestamp or Unix timestamp
     * @param {number} [resolution=30] - Grid resolution in meters
     * @returns {Promise<Object>} Heat map data
     * 
     * Response format:
     * {
     *   center: { lat, lon },
     *   radius: number,
     *   resolution: number,
     *   timestamp: string,
     *   grid: {
     *     type: 'FeatureCollection',
     *     features: [{
     *       type: 'Feature',
     *       geometry: {
     *         type: 'Polygon',
     *         coordinates: [...]
     *       },
     *       properties: {
     *         status: 'clear' | 'marginal' | 'dead',
     *         visible_count: number,
     *         center: { lat, lon }
     *       }
     *     }]
     *   },
     *   buildings: {
     *     type: 'FeatureCollection',
     *     features: [...]
     *   }
     * }
     */
    async getHeatMap(lat, lon, radius = 500, timestamp = null, resolution = 30) {
        const body = {
            lat: parseFloat(lat),
            lon: parseFloat(lon),
            radius_m: parseInt(radius, 10),
            spacing_m: parseInt(resolution, 10)
        };
        
        if (timestamp) {
            body.timestamp = timestamp;
        }
        
        return this.request('/heatmap', {
            method: 'POST',
            body: JSON.stringify(body),
            _timeoutMs: 60000,
            _maxRetries: 1
        });
    }

    /**
     * Plan a route and analyze satellite connectivity along the path.
     * @param {Object} origin - { lat, lon } or { address }
     * @param {Object} destination - { lat, lon } or { address }
     * @param {number} [sampleInterval=500] - Sampling interval in meters
     * @param {string|null} [timeUtc=null] - Optional ISO UTC timestamp
     * @returns {Promise<Object>} Route plan response
     */
    async planRoute(origin, destination, sampleInterval = 500, timeUtc = null, signal = null) {
        const interval = Number.parseFloat(sampleInterval);
        if (!Number.isFinite(interval) || interval <= 0) {
            throw new TypeError('sampleInterval must be a positive number');
        }

        const body = {
            origin: this.normalizeRouteLocation(origin, 'origin'),
            destination: this.normalizeRouteLocation(destination, 'destination'),
            sample_interval_m: interval
        };

        if (timeUtc) {
            body.time_utc = timeUtc;
        }

        return this.request('/route/plan', {
            method: 'POST',
            body: JSON.stringify(body),
            signal,
            _timeoutMs: 120000,
            _maxRetries: 1
        });
    }
    
    /**
     * Get currently visible satellites for a position
     * @param {number} lat - Latitude
     * @param {number} lon - Longitude
     * @param {string|number} [timestamp] - ISO timestamp or Unix timestamp
     * @returns {Promise<Object>} Satellite data
     * 
     * Response format:
     * {
     *   timestamp: string,
     *   location: { lat, lon },
     *   satellites: [{
     *     id: string,
     *     name: string,
     *     constellation: string,
     *     azimuth: number,
     *     elevation: number,
     *     snr: number,
     *     visible: boolean,
     *     obstructed: boolean
     *   }]
     * }
     */
    async getVisibleSatellites(lat, lon, timestamp = null) {
        const params = new URLSearchParams({
            lat: lat.toString(),
            lon: lon.toString()
        });
        
        if (timestamp) {
            params.append('timestamp', timestamp.toString());
        }
        
        return this.request(`/satellites?${params.toString()}`, {
            method: 'GET'
        });
    }

    /**
     * Get Starlink constellation map points.
     * @param {string|number|null} [timestamp] - Optional ISO timestamp
     * @param {number|null} [limit] - Optional max number of satellites
     * @returns {Promise<Object>} Constellation map payload
     */
    async getConstellationMap(timestamp = null, limit = null) {
        const params = new URLSearchParams();

        if (timestamp) {
            params.append('timestamp', timestamp.toString());
        }

        if (limit != null && Number.isFinite(Number(limit))) {
            const normalizedLimit = Math.max(100, Math.floor(Number(limit)));
            params.append('limit', normalizedLimit.toString());
        }

        const query = params.toString();
        return this.request(
            `/satellites/constellation/map${query ? `?${query}` : ''}`,
            {
                method: 'GET',
                _timeoutMs: 45000,
                _maxRetries: 1
            }
        );
    }
    
    /**
     * Check API health status
     * @returns {Promise<Object>} Health status
     * 
     * Response format:
     * {
     *   status: 'healthy' | 'degraded' | 'unhealthy',
     *   version: string,
     *   timestamp: string,
     *   uptime: number
     * }
     */
    async healthCheck() {
        return this.request('/health', {
            method: 'GET'
        });
    }
    
    /**
     * Batch analyze multiple positions
     * @param {Array<{lat: number, lon: number}>} positions - Array of positions
     * @param {string|number} [timestamp] - ISO timestamp or Unix timestamp
     * @returns {Promise<Array>} Array of analysis results
     */
    async batchAnalyze(positions, timestamp = null) {
        const body = {
            positions: positions.map(p => ({
                lat: parseFloat(p.lat),
                lon: parseFloat(p.lon)
            }))
        };
        
        if (timestamp) {
            body.timestamp = timestamp;
        }
        
        return this.request('/batch-analyze', {
            method: 'POST',
            body: JSON.stringify(body)
        });
    }
    
    /**
     * Get time series analysis for a position
     * @param {number} lat - Latitude
     * @param {number} lon - Longitude
     * @param {string} startTime - Start ISO timestamp
     * @param {string} endTime - End ISO timestamp
     * @param {number} [interval=900] - Interval in seconds (default 15 min)
     * @returns {Promise<Object>} Time series data
     */
    async getTimeSeries(lat, lon, startTime, endTime, interval = 900) {
        const params = new URLSearchParams({
            lat: lat.toString(),
            lon: lon.toString(),
            start: startTime,
            end: endTime,
            interval: interval.toString()
        });
        
        return this.request(`/timeseries?${params.toString()}`, {
            method: 'GET'
        });
    }
}

/**
 * Custom API Error class
 */
class APIError extends Error {
    /**
     * Create an API error
     * @param {string} message - Error message
     * @param {number} status - HTTP status code
     * @param {Object} data - Additional error data
     */
    constructor(message, status = 500, data = {}) {
        super(message);
        this.name = 'APIError';
        this.status = status;
        this.data = data;
    }
    
    /**
     * Check if error is a client error (4xx)
     * @returns {boolean}
     */
    isClientError() {
        return this.status >= 400 && this.status < 500;
    }
    
    /**
     * Check if error is a server error (5xx)
     * @returns {boolean}
     */
    isServerError() {
        return this.status >= 500 && this.status < 600;
    }
    
    /**
     * Check if error is a network error
     * @returns {boolean}
     */
    isNetworkError() {
        return this.status === 0 || this.status === 408;
    }
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { APIClient, APIError };
}

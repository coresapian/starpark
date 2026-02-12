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
        this.timeout = options.timeout || 10000;
        this.maxRetries = options.maxRetries || 3;
        this.retryDelay = options.retryDelay || 1000;
        
        // Request queue for offline support
        this.requestQueue = [];
        this.isOnline = navigator.onLine;
        
        // Bind online/offline events
        window.addEventListener('online', () => {
            this.isOnline = true;
            this.processQueue();
        });
        window.addEventListener('offline', () => {
            this.isOnline = false;
        });
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
        const url = `${this.baseURL}${endpoint}`;
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), this.timeout);
        
        try {
            const response = await fetch(url, {
                ...options,
                signal: controller.signal,
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    ...options.headers
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
            
            // Parse JSON response
            const data = await response.json();
            
            // Check for cached response from service worker
            const isCached = response.headers.get('X-SW-Cached') === 'true';
            if (isCached) {
                data._cached = true;
            }
            
            return data;
            
        } catch (error) {
            clearTimeout(timeoutId);
            
            // Handle abort/timeout
            if (error.name === 'AbortError') {
                throw new APIError('Request timeout', 408);
            }
            
            // Handle network errors with retry
            if (attempt < this.maxRetries && this.shouldRetry(error)) {
                await this.delay(this.retryDelay * attempt);
                return this.request(endpoint, options, attempt + 1);
            }
            
            throw error;
        }
    }
    
    /**
     * Determine if a request should be retried
     * @private
     * @param {Error} error - The error that occurred
     * @returns {boolean} Whether to retry
     */
    shouldRetry(error) {
        // Retry on network errors and 5xx status codes
        if (error instanceof APIError) {
            return error.status >= 500 || error.status === 408;
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
            try {
                const result = await this.request(endpoint, options);
                resolve(result);
            } catch (error) {
                reject(error);
            }
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
        return new Promise((resolve, reject) => {
            this.requestQueue.push({ endpoint, options, resolve, reject });
        });
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
            radius: parseInt(radius, 10),
            resolution: parseInt(resolution, 10)
        };
        
        if (timestamp) {
            body.timestamp = timestamp;
        }
        
        return this.request('/heatmap', {
            method: 'POST',
            body: JSON.stringify(body)
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

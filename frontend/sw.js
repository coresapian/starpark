/**
 * LinkSpot Service Worker
 * Provides offline caching and network-first API strategies
 * @version 1.0.0
 */

const CACHE_NAME = 'linkspot-v2';
const STATIC_CACHE = 'linkspot-static-v2';
const API_CACHE = 'linkspot-api-v2';

// Static assets to cache on install
const STATIC_ASSETS = [
    '/',
    '/index.html',
    '/css/styles.css',
    '/js/app.js',
    '/js/api-client.js',
    '/js/sky-plot.js',
    '/manifest.json',
    'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
    'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'
];

// API routes that should use network-first strategy
const API_ROUTES = [
    '/api/v1/analyze',
    '/api/v1/heatmap',
    '/api/v1/satellites',
    '/api/v1/health'
];

/**
 * Check if a URL is an API request
 * @param {string} url - URL to check
 * @returns {boolean} True if URL is an API endpoint
 */
function isApiRequest(url) {
    return API_ROUTES.some(route => url.includes(route));
}

/**
 * Check if a URL is a static asset
 * @param {string} url - URL to check
 * @returns {boolean} True if URL is a static asset
 */
function isStaticAsset(url) {
    return STATIC_ASSETS.some(asset => url.includes(asset)) ||
           url.includes('.css') ||
           url.includes('.js') ||
           url.includes('.png') ||
           url.includes('.jpg') ||
           url.includes('.svg') ||
           url.includes('.json');
}

// Install event - cache static assets
self.addEventListener('install', (event) => {
    console.log('[SW] Installing...');
    
    event.waitUntil(
        caches.open(STATIC_CACHE)
            .then(cache => {
                console.log('[SW] Caching static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => {
                console.log('[SW] Static assets cached');
                return self.skipWaiting();
            })
            .catch(error => {
                console.error('[SW] Cache failed:', error);
            })
    );
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
    console.log('[SW] Activating...');
    
    event.waitUntil(
        caches.keys()
            .then(cacheNames => {
                return Promise.all(
                    cacheNames
                        .filter(name => {
                            return name.startsWith('linkspot-') && 
                                   name !== STATIC_CACHE && 
                                   name !== API_CACHE;
                        })
                        .map(name => {
                            console.log('[SW] Deleting old cache:', name);
                            return caches.delete(name);
                        })
                );
            })
            .then(() => {
                console.log('[SW] Claiming clients');
                return self.clients.claim();
            })
    );
});

// Fetch event - handle requests with appropriate strategies
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);
    
    // Skip non-GET requests for API (POST handled separately)
    if (request.method !== 'GET' && !isApiRequest(url.href)) {
        return;
    }
    
    // API requests: Network-first with cache fallback
    if (isApiRequest(url.href)) {
        event.respondWith(networkFirstStrategy(request));
        return;
    }
    
    // Static assets: Cache-first with network fallback
    if (isStaticAsset(url.href)) {
        event.respondWith(cacheFirstStrategy(request));
        return;
    }
    
    // Default: Network with cache fallback
    event.respondWith(networkWithCacheFallback(request));
});

/**
 * Network-first strategy for API calls
 * Tries network first, falls back to cache if offline
 * @param {Request} request - Fetch request
 * @returns {Promise<Response>} Response from network or cache
 */
async function networkFirstStrategy(request) {
    try {
        const networkResponse = await fetch(request);
        
        if (networkResponse.ok) {
            // Cache successful API responses
            const cache = await caches.open(API_CACHE);
            cache.put(request, networkResponse.clone());
        }
        
        return networkResponse;
    } catch (error) {
        console.log('[SW] Network failed, trying cache:', request.url);
        
        const cachedResponse = await caches.match(request);
        
        if (cachedResponse) {
            // Add header to indicate cached response
            const headers = new Headers(cachedResponse.headers);
            headers.set('X-SW-Cached', 'true');
            
            return new Response(cachedResponse.body, {
                status: cachedResponse.status,
                statusText: cachedResponse.statusText,
                headers: headers
            });
        }
        
        // Return offline response for API
        return new Response(
            JSON.stringify({
                error: 'Offline',
                message: 'You are currently offline. Please check your connection.',
                cached: false
            }),
            {
                status: 503,
                headers: { 'Content-Type': 'application/json' }
            }
        );
    }
}

/**
 * Cache-first strategy for static assets
 * @param {Request} request - Fetch request
 * @returns {Promise<Response>} Response from cache or network
 */
async function cacheFirstStrategy(request) {
    const cachedResponse = await caches.match(request);
    
    if (cachedResponse) {
        return cachedResponse;
    }
    
    try {
        const networkResponse = await fetch(request);
        
        if (networkResponse.ok) {
            const cache = await caches.open(STATIC_CACHE);
            cache.put(request, networkResponse.clone());
        }
        
        return networkResponse;
    } catch (error) {
        console.error('[SW] Fetch failed:', error);
        throw error;
    }
}

/**
 * Network with cache fallback
 * @param {Request} request - Fetch request
 * @returns {Promise<Response>} Response from network or cache
 */
async function networkWithCacheFallback(request) {
    try {
        const networkResponse = await fetch(request);
        return networkResponse;
    } catch (error) {
        const cachedResponse = await caches.match(request);
        
        if (cachedResponse) {
            return cachedResponse;
        }
        
        throw error;
    }
}

// Background sync for offline form submissions
self.addEventListener('sync', (event) => {
    if (event.tag === 'sync-analysis-requests') {
        event.waitUntil(syncAnalysisRequests());
    }
});

/**
 * Sync pending analysis requests when back online
 */
async function syncAnalysisRequests() {
    // Implementation for background sync
    // Would retrieve pending requests from IndexedDB and send them
    console.log('[SW] Syncing analysis requests...');
}

// Push notification support (future feature)
self.addEventListener('push', (event) => {
    if (event.data) {
        const data = event.data.json();
        
        event.waitUntil(
            self.registration.showNotification(data.title, {
                body: data.body,
                icon: 'assets/icon-192.png',
                badge: 'assets/badge-72.png',
                data: data.data
            })
        );
    }
});

// Notification click handler
self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    
    event.waitUntil(
        clients.openWindow(event.notification.data?.url || '/')
    );
});

// Message handler from main thread
self.addEventListener('message', (event) => {
    if (event.data === 'skipWaiting') {
        self.skipWaiting();
    }
    
    if (event.data.type === 'CACHE_ASSETS') {
        caches.open(STATIC_CACHE).then(cache => {
            cache.addAll(event.data.assets);
        });
    }
});

/**
 * LinkSpot Electron - Custom Protocol Handler
 * Registers app:// scheme to serve frontend static files
 * and proxy /api/v1/* requests to the configurable backend.
 */

const { protocol, net } = require('electron');
const path = require('path');
const fs = require('fs');
const store = require('./store');

const FRONTEND_DIR = path.join(__dirname, '..', 'frontend');

const MIME_TYPES = {
  '.html': 'text/html',
  '.css': 'text/css',
  '.js': 'application/javascript',
  '.json': 'application/json',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.webmanifest': 'application/manifest+json'
};

// No-op service worker that immediately takes control and does nothing
const NOOP_SW = `
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
`;

// Script injected into <head> to stub out Service Worker registration,
// add a Content-Security-Policy, and wrap geolocation with fallbacks.
// Runs before any other scripts (Leaflet, app.js, etc.).
const HEAD_INJECT = `
<meta http-equiv="Content-Security-Policy" content="default-src 'self' app:; script-src 'self' 'unsafe-inline' https://unpkg.com; style-src 'self' 'unsafe-inline' https://unpkg.com; img-src 'self' data: blob: https://*.basemaps.cartocdn.com https://*.tile.openstreetmap.org https://unpkg.com; connect-src 'self' app: https://nominatim.openstreetmap.org https://ipapi.co https://freeipapi.com; font-src 'self' data:;">
<script>
// 1. Stub navigator.serviceWorker.register — app:// doesn't support SW
if (navigator.serviceWorker) {
  const noop = () => Promise.resolve({ scope: '/', unregister: () => Promise.resolve(true) });
  Object.defineProperty(navigator, 'serviceWorker', {
    value: new Proxy(navigator.serviceWorker, {
      get(target, prop) {
        if (prop === 'register') return noop;
        if (prop === 'getRegistrations') return () => Promise.resolve([]);
        const val = target[prop];
        return typeof val === 'function' ? val.bind(target) : val;
      }
    }),
    configurable: true
  });
}

// 2. Wrap geolocation with robust fallback chain.
//    navigator.geolocation is broken in Electron on macOS:
//    - No Google API key → 403 from googleapis.com
//    - macOS permission prompt often never fires, or hangs indefinitely
//    Strategy: try native geo with a hard timeout, then fall back to
//    IP geolocation via IPC (main process net.fetch, bypasses CORS).
(function() {
  if (!navigator.geolocation) return;
  var _getCurrentPosition = navigator.geolocation.getCurrentPosition.bind(navigator.geolocation);

  function ipFallback(success, error, originalErr) {
    if (!window.electronAPI || !window.electronAPI.getIPLocation) {
      if (error) error(originalErr);
      return;
    }
    window.electronAPI.getIPLocation().then(function(loc) {
      if (loc && loc.lat && loc.lon) {
        success({
          coords: {
            latitude: loc.lat,
            longitude: loc.lon,
            accuracy: 5000,
            altitude: null,
            altitudeAccuracy: null,
            heading: null,
            speed: null
          },
          timestamp: Date.now()
        });
      } else if (error) {
        error(originalErr);
      }
    }).catch(function() {
      if (error) error(originalErr);
    });
  }

  navigator.geolocation.getCurrentPosition = function(success, error, options) {
    var settled = false;

    // Hard timeout — macOS can hang indefinitely without calling either callback
    var timeout = setTimeout(function() {
      if (settled) return;
      settled = true;
      console.warn('[LinkSpot] Native geolocation timed out, using IP fallback');
      var err = { code: 3, message: 'Geolocation timed out (Electron/macOS)' };
      ipFallback(success, error, err);
    }, 6000);

    _getCurrentPosition(
      function(pos) {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        success(pos);
      },
      function(err) {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);

        if (err.code === 1 && window.electronAPI) {
          // PERMISSION_DENIED — show system settings dialog, then IP fallback
          window.electronAPI.promptLocationPermission();
          ipFallback(success, error, err);
          return;
        }

        // code 2 (POSITION_UNAVAILABLE / Google 403) or code 3 (TIMEOUT) — IP fallback
        console.warn('[LinkSpot] Native geolocation failed (code ' + err.code + '), using IP fallback');
        ipFallback(success, error, err);
      },
      options
    );
  };
})();
</script>`;

/**
 * Register the app:// scheme as privileged before app is ready.
 * Must be called before app.whenReady().
 */
function registerScheme() {
  protocol.registerSchemesAsPrivileged([
    {
      scheme: 'app',
      privileges: {
        standard: true,
        secure: true,
        supportFetchAPI: true,
        corsEnabled: true,
        stream: true
      }
    }
  ]);
}

/**
 * Set up the protocol handler after app is ready.
 * Serves static files from frontend/ and proxies API requests.
 */
function setupProtocolHandler() {
  protocol.handle('app', async (request) => {
    const url = new URL(request.url);
    const pathname = url.pathname;

    // Intercept service worker registration — return no-op SW
    if (pathname === '/sw.js') {
      return new Response(NOOP_SW, {
        headers: { 'Content-Type': 'application/javascript' }
      });
    }

    // Proxy API requests to the backend
    if (pathname.startsWith('/api/')) {
      return proxyToBackend(request, pathname + url.search);
    }

    // Serve static files from frontend/
    return serveStaticFile(pathname);
  });
}

/**
 * Proxy a request to the configured backend URL.
 */
async function proxyToBackend(request, pathAndQuery) {
  const backendURL = store.get('backendURL');
  const targetURL = `${backendURL}${pathAndQuery}`;

  try {
    const fetchOptions = {
      method: request.method,
      headers: request.headers
    };

    // Forward body for POST/PUT/PATCH
    if (['POST', 'PUT', 'PATCH'].includes(request.method) && request.body) {
      fetchOptions.body = request.body;
      fetchOptions.duplex = 'half';
    }

    return await net.fetch(targetURL, fetchOptions);
  } catch (error) {
    return new Response(
      JSON.stringify({
        error: 'Backend Unreachable',
        message: `Cannot connect to ${backendURL}. Check your backend URL in Preferences.`,
        detail: error.message
      }),
      {
        status: 502,
        headers: { 'Content-Type': 'application/json' }
      }
    );
  }
}

/**
 * Serve a static file from the frontend/ directory.
 */
function serveStaticFile(pathname) {
  // Default to index.html for root or SPA routes
  let filePath;
  if (pathname === '/' || pathname === '') {
    filePath = path.join(FRONTEND_DIR, 'index.html');
  } else {
    // Sanitize: prevent directory traversal
    const safePath = path.normalize(pathname).replace(/^(\.\.[\/\\])+/, '');
    filePath = path.join(FRONTEND_DIR, safePath);
  }

  // Check file exists
  if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
    // SPA fallback: serve index.html for unknown paths
    filePath = path.join(FRONTEND_DIR, 'index.html');
  }

  const ext = path.extname(filePath).toLowerCase();
  const mimeType = MIME_TYPES[ext] || 'application/octet-stream';
  let body = fs.readFileSync(filePath);

  // Inject SW stub + CSP into index.html before any scripts run
  if (path.basename(filePath) === 'index.html') {
    let html = body.toString('utf-8');
    html = html.replace('<head>', '<head>' + HEAD_INJECT);
    body = Buffer.from(html, 'utf-8');
  }

  return new Response(body, {
    status: 200,
    headers: { 'Content-Type': mimeType }
  });
}

module.exports = { registerScheme, setupProtocolHandler };

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
  const body = fs.readFileSync(filePath);

  return new Response(body, {
    status: 200,
    headers: { 'Content-Type': mimeType }
  });
}

module.exports = { registerScheme, setupProtocolHandler };

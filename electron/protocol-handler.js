/**
 * LinkSpot Electron - Custom Protocol Handler
 * Registers app:// scheme to serve frontend static files
 * and proxy /api/v1/* requests to the configurable backend.
 */

const { protocol, net } = require('electron');
const path = require('path');
const fs = require('fs');
const store = require('./store');

const LEGACY_FRONTEND_DIR = path.join(__dirname, '..', 'frontend');
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

const SAFE_PROXY_METHODS = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']);
const SAFE_PROXY_HEADERS = new Set([
  'accept',
  'content-type',
  'content-length',
  'authorization',
  'x-request-id',
  'x-api-key'
]);
const MAX_PROXY_BODY_BYTES = 1_000_000;

// TODO: Replace unsafe inline stub with nonce-protected, externalized bootstrap once CSP is tightened.
// No-op service worker that immediately takes control and does nothing
const NOOP_SW = `
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
`;

// Script injected into <head> to stub out Service Worker registration
// and add a Content-Security-Policy.
// TODO: Remove `unsafe-inline` from CSP by moving injected stub to a separate, hashed script asset.
// Runs before any other scripts (Leaflet, app.js, etc.).
const HEAD_INJECT = `
<meta http-equiv="Content-Security-Policy" content="default-src 'self' app:; script-src 'self' 'unsafe-inline' https://unpkg.com; style-src 'self' 'unsafe-inline' https://unpkg.com https://fonts.googleapis.com; img-src 'self' data: blob: https://*.basemaps.cartocdn.com https://*.tile.openstreetmap.org https://unpkg.com; connect-src 'self' app: https://nominatim.openstreetmap.org https://router.project-osrm.org; font-src 'self' data: https://fonts.gstatic.com;">
<script>
// Stub navigator.serviceWorker.register — app:// doesn't support SW
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

// TODO: Consider locking this handler to trusted origins only to prevent custom-scheme abuse from unexpected protocol consumers.

/**
 * Set up the protocol handler after app is ready.
 * Serves static files from frontend/ and proxies API requests.
 */
function setupProtocolHandler() {
  protocol.handle('app', async (request) => {
    let url;
    try {
      url = new URL(request.url);
    } catch {
      return new Response('Malformed URL', { status: 400 });
    }
    const pathname = url.pathname;

    // Intercept service worker registration — return no-op SW
    if (pathname === '/sw.js' || pathname === '/legacy/sw.js') {
      return new Response(NOOP_SW, {
        headers: { 'Content-Type': 'application/javascript' }
      });
    }

    // Proxy API requests to the backend
    if (pathname.startsWith('/api/')) {
      return proxyToBackend(request, pathname + url.search);
    }

    if (pathname === '/legacy' || pathname.startsWith('/legacy/')) {
      const legacyPath = pathname === '/legacy' ? '/legacy/' : pathname;
      return serveStaticFile(legacyPath.replace(/^\/legacy/, ''), LEGACY_FRONTEND_DIR);
    }

    return serveStaticFile(pathname, getDefaultFrontendDir());
  });
}

/**
 * Proxy a request to the configured backend URL.
 */
async function proxyToBackend(request, pathAndQuery) {
  const backendURL = String(store.get('backendURL') || '').trim();
  let parsedBackend;
  try {
    parsedBackend = new URL(backendURL);
  } catch {
    return new Response(
      JSON.stringify({ error: 'Invalid Backend URL' }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    );
  }
  if (!['http:', 'https:'].includes(parsedBackend.protocol)) {
    return new Response(
      JSON.stringify({ error: 'Invalid Backend Protocol' }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    );
  }

  const method = String(request.method || 'GET').toUpperCase();
  if (!SAFE_PROXY_METHODS.has(method)) {
    return new Response(
      JSON.stringify({ error: 'Unsupported Method', detail: method }),
      { status: 405, headers: { 'Content-Type': 'application/json' } }
    );
  }
  if (!pathAndQuery.startsWith('/api/')) {
    return new Response(
      JSON.stringify({ error: 'Unsupported Path' }),
      { status: 400, headers: { 'Content-Type': 'application/json' } }
    );
  }
  const targetURL = `${backendURL.replace(/\/+$/, '')}${pathAndQuery}`;

  try {
    const proxyHeaders = {};
    for (const [key, value] of request.headers.entries()) {
      const normalized = key.toLowerCase();
      if (SAFE_PROXY_HEADERS.has(normalized)) {
        proxyHeaders[key] = value;
      }
    }
    const contentLength = Number.parseInt(proxyHeaders['content-length'] || proxyHeaders['Content-Length'] || '0', 10);
    if (Number.isFinite(contentLength) && contentLength > MAX_PROXY_BODY_BYTES) {
      return new Response(
        JSON.stringify({ error: 'Payload too large' }),
        { status: 413, headers: { 'Content-Type': 'application/json' } }
      );
    }

    const fetchOptions = {
      method,
      headers: proxyHeaders
    };

    // Forward body for POST/PUT/PATCH
    if (['POST', 'PUT', 'PATCH'].includes(method) && request.body) {
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
function getDefaultFrontendDir() {
  return LEGACY_FRONTEND_DIR;
}

function serveStaticFile(pathname, baseDir) {
  // Default to index.html for root or SPA routes
  let filePath;
  if (pathname === '/' || pathname === '') {
    filePath = path.join(baseDir, 'index.html');
  } else {
    let decodedPath = pathname;
    try {
      decodedPath = decodeURIComponent(pathname);
    } catch {
      return new Response('Bad request', { status: 400 });
    }
    if (decodedPath.includes('..') || decodedPath.includes('\0')) {
      return new Response('Forbidden', { status: 403 });
    }
    const safePath = path.normalize(decodedPath).replace(/^(\.\.[\/\\])+/, '');
    filePath = path.join(baseDir, safePath);
  }

  // Prevent directory traversal — resolved path must stay within the selected frontend root
  const resolvedPath = path.resolve(filePath);
  const resolvedFrontend = path.resolve(baseDir);
  if (!resolvedPath.startsWith(resolvedFrontend + path.sep) && resolvedPath !== resolvedFrontend) {
    filePath = path.join(baseDir, 'index.html');
  }

  // Check file exists
  if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
    // SPA fallback: serve index.html for unknown paths
    filePath = path.join(baseDir, 'index.html');
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

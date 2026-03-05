/**
 * LinkSpot Electron - Settings Store
 * Persistent settings via electron-store
 */

const Store = require('electron-store');

function normalizeBackendURL(rawValue) {
  const value = String(rawValue || '').trim().replace(/\/+$/, '');
  if (!value) return 'http://localhost:8000';
  const parsed = new URL(value);
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error('Backend URL must use HTTP or HTTPS');
  }
  return parsed.toString().replace(/\/$/, '');
}

function normalizeSettingsPatch(patch = {}) {
  const normalized = {};
  if (Object.prototype.hasOwnProperty.call(patch, 'backendURL')) {
    normalized.backendURL = normalizeBackendURL(patch.backendURL);
  }
  if (Object.prototype.hasOwnProperty.call(patch, 'notifications')) {
    normalized.notifications = Boolean(patch.notifications);
  }
  if (Object.prototype.hasOwnProperty.call(patch, 'autoUpdateEnabled')) {
    normalized.autoUpdateEnabled = Boolean(patch.autoUpdateEnabled);
  }
  if (Object.prototype.hasOwnProperty.call(patch, 'autoStartLocalBackend')) {
    normalized.autoStartLocalBackend = Boolean(patch.autoStartLocalBackend);
  }
  return normalized;
}

const schema = {
  backendURL: {
    type: 'string',
    default: 'http://localhost:8000'
  },
  notifications: {
    type: 'boolean',
    default: true
  },
  autoUpdateEnabled: {
    type: 'boolean',
    default: true
  },
  autoStartLocalBackend: {
    type: 'boolean',
    default: true
  },
  windowBounds: {
    type: 'object',
    properties: {
      x: { type: 'number' },
      y: { type: 'number' },
      width: { type: 'number' },
      height: { type: 'number' }
    },
    default: {}
  }
};

const store = new Store({
  schema,
  migrations: {
    '1.0.1': (s) => {
      const current = s.get('backendURL');
      try {
        s.set('backendURL', normalizeBackendURL(current));
      } catch {
        s.set('backendURL', 'http://localhost:8000');
      }
    }
  }
});

store.normalizeBackendURL = normalizeBackendURL;
store.normalizeSettingsPatch = normalizeSettingsPatch;

module.exports = store;

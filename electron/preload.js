/**
 * LinkSpot Electron - Preload Script
 * Exposes safe APIs to the renderer via contextBridge.
 */

const { contextBridge, ipcRenderer } = require('electron');

function registerListener(channel, callback, mapper = (...args) => args) {
  if (typeof callback !== 'function') {
    return () => {};
  }
  const handler = (...args) => {
    const mapped = mapper(...args);
    if (Array.isArray(mapped)) {
      callback(...mapped);
      return;
    }
    callback(mapped);
  };
  ipcRenderer.on(channel, handler);
  return () => ipcRenderer.removeListener(channel, handler);
}

contextBridge.exposeInMainWorld('electronAPI', {
  // Platform info
  platform: process.platform,
  isElectron: true,

  // Settings
  getSettings: () => ipcRenderer.invoke('get-settings'),
  setSettings: (settings) => ipcRenderer.invoke('set-settings', settings),
  testBackend: (url) => ipcRenderer.invoke('test-backend', url),
  startLocalBackend: () => ipcRenderer.invoke('start-local-backend'),

  // Location & Permissions
  promptLocationPermission: () => ipcRenderer.invoke('prompt-location-permission'),

  // Notifications
  showNotification: (opts) => ipcRenderer.invoke('show-notification', opts),

  // Menu command listeners
  onFocusSearch: (callback) => {
    return registerListener('focus-search', callback, () => []);
  },
  onRefreshMap: (callback) => {
    return registerListener('refresh-map', callback, () => []);
  },
  onGoToLocation: (callback) => {
    return registerListener('go-to-location', callback, () => []);
  },
  onSettingsChanged: (callback) => {
    return registerListener('settings-changed', callback, (_event, settings) => settings);
  },
  onBackendStatus: (callback) => {
    return registerListener('backend-status', callback, (_event, status) => {
      if (!status || typeof status !== 'object') {
        return { connected: false, overall: 'unknown', components: [] };
      }
      return {
        connected: Boolean(status.connected),
        overall: status.overall || 'unknown',
        components: Array.isArray(status.components) ? status.components : []
      };
    });
  },
  onBackendBootstrapStatus: (callback) => {
    return registerListener('backend-bootstrap-status', callback, (_event, payload) => {
      if (!payload || typeof payload !== 'object') {
        return { phase: 'unknown', message: 'No status available' };
      }
      return {
        phase: String(payload.phase || 'unknown'),
        message: String(payload.message || ''),
        timestamp: Number(payload.timestamp || Date.now())
      };
    });
  }
});

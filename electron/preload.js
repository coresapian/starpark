/**
 * LinkSpot Electron - Preload Script
 * Exposes safe APIs to the renderer via contextBridge.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  // Platform info
  platform: process.platform,
  isElectron: true,

  // Settings
  getSettings: () => ipcRenderer.invoke('get-settings'),
  setSettings: (settings) => ipcRenderer.invoke('set-settings', settings),
  testBackend: (url) => ipcRenderer.invoke('test-backend', url),

  // Location & Permissions
  getIPLocation: () => ipcRenderer.invoke('get-ip-location'),
  promptLocationPermission: () => ipcRenderer.invoke('prompt-location-permission'),

  // Notifications
  showNotification: (opts) => ipcRenderer.invoke('show-notification', opts),

  // Menu command listeners
  onFocusSearch: (callback) => {
    ipcRenderer.on('focus-search', () => callback());
    return () => ipcRenderer.removeAllListeners('focus-search');
  },
  onRefreshMap: (callback) => {
    ipcRenderer.on('refresh-map', () => callback());
    return () => ipcRenderer.removeAllListeners('refresh-map');
  },
  onGoToLocation: (callback) => {
    ipcRenderer.on('go-to-location', () => callback());
    return () => ipcRenderer.removeAllListeners('go-to-location');
  },
  onSettingsChanged: (callback) => {
    ipcRenderer.on('settings-changed', (_event, settings) => callback(settings));
    return () => ipcRenderer.removeAllListeners('settings-changed');
  },
  onBackendStatus: (callback) => {
    ipcRenderer.on('backend-status', (_event, status) => callback(status));
    return () => ipcRenderer.removeAllListeners('backend-status');
  }
});

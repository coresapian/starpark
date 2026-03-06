/**
 * LinkSpot Electron - Main Process
 * Creates the main window, registers protocol, and manages app lifecycle.
 */

const { app, BrowserWindow, ipcMain, Notification, session, dialog, shell, net } = require('electron');
const fs = require('fs');
const path = require('path');
const log = require('electron-log');
const windowStateKeeper = require('electron-window-state');
const { registerScheme, setupProtocolHandler } = require('./protocol-handler');
const store = require('./store');
const { createMenu } = require('./menu');
const { createTray, destroyTray } = require('./tray');
const { setupUpdater } = require('./updater');
const { createLocalBackendManager } = require('./local-backend');

// Configure logging
log.transports.file.level = 'info';
log.transports.console.level = 'debug';

// Register custom protocol scheme — must happen before app.whenReady()
registerScheme();

let mainWindow = null;
let settingsWindow = null;
let backendPollIntervalId = null;
let localBackendManager = null;

function resolvePreloadPath() {
  const emittedPath = path.join(__dirname, 'dist', 'preload.js');
  if (fs.existsSync(emittedPath)) {
    return emittedPath;
  }
  return path.join(__dirname, 'preload.js');
}

function isTrustedRenderer(webContents) {
  try {
    const currentURL = new URL(webContents.getURL());
    return currentURL.protocol === 'app:' && currentURL.host === 'linkspot';
  } catch {
    return false;
  }
}

/**
 * Create the main application window.
 */
function createMainWindow() {
  const mainWindowState = windowStateKeeper({
    defaultWidth: 1280,
    defaultHeight: 800
  });

  mainWindow = new BrowserWindow({
    x: mainWindowState.x,
    y: mainWindowState.y,
    width: mainWindowState.width,
    height: mainWindowState.height,
    minWidth: 800,
    minHeight: 600,
    title: 'LinkSpot',
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 16, y: 16 },
    backgroundColor: '#1a1a2e',
    webPreferences: {
      preload: resolvePreloadPath(),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });

  // Track window state
  mainWindowState.manage(mainWindow);

  // Load the app via custom protocol
  mainWindow.loadURL('app://linkspot/').catch((err) => {
    log.error('Failed to load app:// URL:', err);
  });

  mainWindow.webContents.on('did-fail-load', (_event, errorCode, errorDescription) => {
    log.error('Renderer load failed:', errorCode, errorDescription);
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  return mainWindow;
}

/**
 * Create the settings/preferences window.
 */
function createSettingsWindow() {
  if (settingsWindow) {
    settingsWindow.focus();
    return;
  }

  settingsWindow = new BrowserWindow({
    width: 480,
    height: 400,
    resizable: false,
    minimizable: false,
    maximizable: false,
    title: 'Preferences',
    backgroundColor: '#1a1a2e',
    parent: mainWindow,
    modal: false,
    show: false,
    webPreferences: {
      preload: resolvePreloadPath(),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });

  settingsWindow.loadFile(path.join(__dirname, 'settings.html'));

  settingsWindow.once('ready-to-show', () => {
    settingsWindow.show();
  });

  settingsWindow.on('closed', () => {
    settingsWindow = null;
  });
}

// ============================================
// IPC HANDLERS
// ============================================

ipcMain.handle('get-settings', () => {
  return {
    backendURL: store.get('backendURL'),
    notifications: store.get('notifications'),
    autoStartLocalBackend: store.get('autoStartLocalBackend')
  };
});

ipcMain.handle('set-settings', (_event, settings) => {
  try {
    const normalized = store.normalizeSettingsPatch(settings);
    Object.entries(normalized).forEach(([key, value]) => store.set(key, value));
  } catch (error) {
    return { success: false, error: error.message || 'Invalid settings payload' };
  }

  // Notify the main window
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('settings-changed', {
      backendURL: store.get('backendURL'),
      notifications: store.get('notifications'),
      autoStartLocalBackend: store.get('autoStartLocalBackend')
    });
  }

  return { success: true };
});

ipcMain.handle('test-backend', async (_event, url) => {
  try {
    const normalized = store.normalizeBackendURL(url);
    const response = await net.fetch(`${normalized}/api/v1/health`, {
      method: 'GET'
    });
    const data = await response.json();
    return { success: true, status: data.status || 'connected' };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

ipcMain.handle('prompt-location-permission', async () => {
  const { response } = await dialog.showMessageBox(mainWindow, {
    type: 'info',
    title: 'Location Access Required',
    message: 'LinkSpot needs access to your location to center the map and analyze satellite visibility.',
    detail: 'Please enable Location Services for LinkSpot in System Settings > Privacy & Security > Location Services.',
    buttons: ['Open System Settings', 'Cancel'],
    defaultId: 0,
    cancelId: 1
  });

  if (response === 0) {
    shell.openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_LocationServices');
  }

  return { opened: response === 0 };
});

ipcMain.handle('show-notification', (_event, opts) => {
  if (!store.get('notifications')) return { shown: false };

  const notification = new Notification({
    title: opts.title || 'LinkSpot',
    body: opts.body || '',
    silent: opts.silent || false
  });
  notification.show();
  return { shown: true };
});

ipcMain.handle('start-local-backend', async () => {
  if (!localBackendManager) {
    return { success: false, error: 'Local backend manager is unavailable.' };
  }
  return localBackendManager.start({ trigger: 'manual' });
});

// ============================================
// APP LIFECYCLE
// ============================================

app.whenReady().then(() => {
  log.info('LinkSpot Electron starting...');

  // In dev mode, patch the Electron.app Info.plist to include NSLocationUsageDescription
  // so macOS can show the location permission prompt
  if (!app.isPackaged) {
    try {
      const { execSync } = require('child_process');
      const plistPath = path.join(
        path.dirname(process.execPath), '..', 'Info.plist'
      );
      if (fs.existsSync(plistPath)) {
        const content = fs.readFileSync(plistPath, 'utf-8');
        if (!content.includes('NSLocationUsageDescription')) {
          execSync(
            `/usr/libexec/PlistBuddy -c "Add :NSLocationUsageDescription string 'LinkSpot needs your location to center the map and analyze satellite visibility.'" "${plistPath}"`,
            { stdio: 'ignore' }
          );
          log.info('Patched dev Electron.app Info.plist with NSLocationUsageDescription');
        }
      }
    } catch (err) {
      log.warn('Could not patch dev Info.plist:', err.message);
    }
  }

  // Register protocol handler
  setupProtocolHandler();

  // Grant permissions for geolocation, notifications, etc.
  const allowedPermissions = ['geolocation', 'notifications', 'media'];
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    callback(isTrustedRenderer(webContents) && allowedPermissions.includes(permission));
  });
  session.defaultSession.setPermissionCheckHandler((webContents, permission) => {
    return isTrustedRenderer(webContents) && allowedPermissions.includes(permission);
  });

  // Create main window
  createMainWindow();

  // Local backend manager for one-click Docker startup
  localBackendManager = createLocalBackendManager({
    app,
    net,
    shell,
    log,
    store,
    onStatus: (status) => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('backend-bootstrap-status', status);
      }
    }
  });

  localBackendManager.autoStartIfEnabled().catch((error) => {
    log.warn('Auto-start local backend failed:', error && error.message ? error.message : error);
  });

  // Create application menu (passes settings window opener)
  createMenu({
    onPreferences: createSettingsWindow,
    getMainWindow: () => mainWindow
  });

  // Create system tray
  createTray({
    onShow: () => {
      if (mainWindow) {
        mainWindow.show();
        mainWindow.focus();
      }
    },
    onPreferences: createSettingsWindow,
    getMainWindow: () => mainWindow
  });

  // Setup auto-updater
  setupUpdater({
    enabled: app.isPackaged && store.get('autoUpdateEnabled') !== false
  });

  // Periodic backend health check — broadcast status to renderer
  let lastBackendStatus = null;
  async function checkBackend() {
    const backendURL = store.get('backendURL');
    let status;
    try {
      const response = await net.fetch(`${backendURL}/api/v1/health/detailed`, { method: 'GET' });
      const payload = await response.json().catch(() => ({}));
      status = {
        connected: response.ok,
        overall: payload.status || 'unknown',
        components: Array.isArray(payload.components) ? payload.components : []
      };
    } catch {
      status = { connected: false, overall: 'unreachable', components: [] };
    }
    if (JSON.stringify(status) !== JSON.stringify(lastBackendStatus)) {
      lastBackendStatus = status;
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('backend-status', status);
      }
    }
  }
  checkBackend();
  const backendIntervalMs = 30000;
  backendPollIntervalId = setInterval(checkBackend, backendIntervalMs);

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow();
    } else if (mainWindow) {
      mainWindow.show();
    }
  });
});

app.on('window-all-closed', () => {
  // On macOS, keep app running in tray
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  destroyTray();
  if (typeof backendPollIntervalId !== 'undefined') {
    clearInterval(backendPollIntervalId);
  }
  localBackendManager = null;
});

// Expose createSettingsWindow for menu module
module.exports = { createSettingsWindow };

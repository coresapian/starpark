/**
 * LinkSpot Electron - Main Process
 * Creates the main window, registers protocol, and manages app lifecycle.
 */

const { app, BrowserWindow, ipcMain, Notification, session, dialog, shell, net } = require('electron');
const path = require('path');
const log = require('electron-log');
const windowStateKeeper = require('electron-window-state');
const { registerScheme, setupProtocolHandler } = require('./protocol-handler');
const store = require('./store');
const { createMenu } = require('./menu');
const { createTray, destroyTray } = require('./tray');
const { setupUpdater } = require('./updater');

// Configure logging
log.transports.file.level = 'info';
log.transports.console.level = 'debug';

// Register custom protocol scheme — must happen before app.whenReady()
registerScheme();

let mainWindow = null;
let settingsWindow = null;

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
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });

  // Track window state
  mainWindowState.manage(mainWindow);

  // Load the app via custom protocol
  mainWindow.loadURL('app://linkspot/index.html');

  // Wire menu commands to the app after page loads
  mainWindow.webContents.on('did-finish-load', () => {
    mainWindow.webContents.executeJavaScript(`
      if (window.electronAPI) {
        window.electronAPI.onFocusSearch(() => {
          const input = document.getElementById('search-input');
          if (input) input.focus();
        });

        window.electronAPI.onRefreshMap(() => {
          if (window.linkSpotApp && window.linkSpotApp.state.currentPosition) {
            const pos = window.linkSpotApp.state.currentPosition;
            window.linkSpotApp.state.lastHeatMapRequest = null;
            window.linkSpotApp.loadHeatMap(pos.lat, pos.lon);
          }
        });

        window.electronAPI.onGoToLocation(() => {
          if (window.linkSpotApp) {
            window.linkSpotApp.centerOnGPS();
          }
        });
      }
      void 0;
    `).catch(err => log.warn('Post-load injection failed:', err));
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
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
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
    notifications: store.get('notifications')
  };
});

ipcMain.handle('set-settings', (_event, settings) => {
  if (settings.backendURL !== undefined) {
    store.set('backendURL', settings.backendURL);
  }
  if (settings.notifications !== undefined) {
    store.set('notifications', settings.notifications);
  }

  // Notify the main window
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('settings-changed', {
      backendURL: store.get('backendURL'),
      notifications: store.get('notifications')
    });
  }

  return { success: true };
});

ipcMain.handle('test-backend', async (_event, url) => {
  try {
    const { net } = require('electron');
    const response = await net.fetch(`${url}/api/v1/health`, {
      method: 'GET'
    });
    const data = await response.json();
    return { success: true, status: data.status || 'connected' };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

ipcMain.handle('get-ip-location', async () => {
  const services = [
    {
      url: 'https://ipapi.co/json/',
      parse: (d) => d.latitude && d.longitude ? { lat: d.latitude, lon: d.longitude, city: d.city } : null
    },
    {
      url: 'https://freeipapi.com/api/json',
      parse: (d) => d.latitude && d.longitude ? { lat: d.latitude, lon: d.longitude, city: d.cityName } : null
    }
  ];

  for (const svc of services) {
    try {
      const resp = await net.fetch(svc.url, { method: 'GET' });
      const data = await resp.json();
      const result = svc.parse(data);
      if (result) {
        log.info(`IP geolocation: ${result.lat}, ${result.lon} (${result.city || 'unknown'})`);
        return result;
      }
    } catch (err) {
      log.warn(`IP geolocation failed for ${svc.url}:`, err.message);
    }
  }
  return null;
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
      const fs = require('fs');
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
    callback(allowedPermissions.includes(permission));
  });
  session.defaultSession.setPermissionCheckHandler((_webContents, permission) => {
    return allowedPermissions.includes(permission);
  });

  // Create main window
  createMainWindow();

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
  setupUpdater();

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
});

// Expose createSettingsWindow for menu module
module.exports = { createSettingsWindow };

/**
 * LinkSpot Electron - System Tray
 */

const { Tray, Menu, nativeImage, app } = require('electron');
const path = require('path');

let tray = null;

/**
 * Create the system tray icon and context menu.
 * @param {Object} options
 * @param {Function} options.onShow - Callback to show main window
 * @param {Function} options.onPreferences - Callback to open preferences
 * @param {Function} options.getMainWindow - Returns the main BrowserWindow
 */
function createTray({ onShow, onPreferences, getMainWindow }) {
  // Use template image for macOS menu bar (auto dark/light mode)
  const iconPath = path.join(__dirname, 'icons', 'trayIconTemplate.png');

  // Create a small fallback icon if file doesn't exist
  let icon;
  try {
    icon = nativeImage.createFromPath(iconPath);
    if (icon.isEmpty()) throw new Error('empty');
  } catch {
    // TODO: Add a bundled monochrome fallback SVG and explicit size variant when native template loading fails.
    // Create a 16x16 template icon programmatically
    icon = nativeImage.createEmpty();
  }

  tray = new Tray(icon);
  tray.setToolTip('LinkSpot');

  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'Show LinkSpot',
      click: () => onShow()
    },
    { type: 'separator' },
    {
      label: 'Quick Analyze',
      click: () => {
        onShow();
        const win = getMainWindow();
        if (win) {
          win.webContents.send('focus-search');
        }
      }
    },
    {
      label: 'My Location',
      click: () => {
        onShow();
        const win = getMainWindow();
        if (win) {
          win.webContents.send('go-to-location');
        }
      }
    },
    { type: 'separator' },
    {
      label: 'Preferences…',
      click: () => onPreferences()
    },
    { type: 'separator' },
    {
      label: 'Quit LinkSpot',
      click: () => app.quit()
    }
  ]);

  tray.setContextMenu(contextMenu);

  // TODO: Update tray context menu state (enabled/disabled actions) based on backend health channel updates.
  tray.on('click', () => onShow());
}

/**
 * Destroy the tray icon.
 */
function destroyTray() {
  if (tray) {
    tray.destroy();
    tray = null;
  }
}

module.exports = { createTray, destroyTray };

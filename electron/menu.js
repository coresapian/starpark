/**
 * LinkSpot Electron - macOS Application Menu
 */

const { app, Menu, shell } = require('electron');

/**
 * Create and set the application menu.
 * @param {Object} options
 * @param {Function} options.onPreferences - Callback to open preferences window
 * @param {Function} options.getMainWindow - Returns the main BrowserWindow
 */
function createMenu({ onPreferences, getMainWindow }) {
  const template = [
    // App menu
    {
      label: app.name,
      submenu: [
        { role: 'about' },
        { type: 'separator' },
        {
          label: 'Preferences…',
          accelerator: 'Cmd+,',
          click: () => onPreferences()
        },
        { type: 'separator' },
        { role: 'services' },
        { type: 'separator' },
        { role: 'hide' },
        { role: 'hideOthers' },
        { role: 'unhide' },
        { type: 'separator' },
        { role: 'quit' }
      ]
    },

    // Edit menu
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        { role: 'selectAll' }
      ]
    },

    // View menu
    {
      label: 'View',
      submenu: [
        {
          label: 'Refresh Map',
          accelerator: 'Cmd+R',
          click: () => {
            const win = getMainWindow();
            if (win) win.webContents.send('refresh-map');
          }
        },
        { type: 'separator' },
        { role: 'togglefullscreen' },
        { type: 'separator' },
        {
          label: 'Developer Tools',
          accelerator: 'Cmd+Alt+I',
          click: () => {
            const win = getMainWindow();
            if (win) win.webContents.toggleDevTools();
          }
        }
      ]
    },

    // Go menu
    {
      label: 'Go',
      submenu: [
        {
          label: 'Search Location',
          accelerator: 'Cmd+F',
          click: () => {
            const win = getMainWindow();
            if (win) win.webContents.send('focus-search');
          }
        },
        {
          label: 'My Location',
          accelerator: 'Cmd+L',
          click: () => {
            const win = getMainWindow();
            if (win) win.webContents.send('go-to-location');
          }
        }
      ]
    },

    // Window menu
    {
      label: 'Window',
      submenu: [
        { role: 'minimize' },
        { role: 'zoom' },
        { type: 'separator' },
        { role: 'front' }
      ]
    },

    // Help menu
    {
      label: 'Help',
      submenu: [
        {
          label: 'LinkSpot Documentation',
          click: () => {
            shell.openExternal('https://github.com/linkspot/linkspot#readme');
          }
        }
      ]
    }
  ];

  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
}

module.exports = { createMenu };

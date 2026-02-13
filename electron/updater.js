/**
 * LinkSpot Electron - Auto-Update via GitHub Releases
 */

const { autoUpdater } = require('electron-updater');
const log = require('electron-log');

/**
 * Setup auto-updater with logging.
 * Updates are checked on launch and can be triggered manually.
 */
function setupUpdater() {
  autoUpdater.logger = log;
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on('checking-for-update', () => {
    log.info('Checking for updates...');
  });

  autoUpdater.on('update-available', (info) => {
    log.info('Update available:', info.version);
  });

  autoUpdater.on('update-not-available', () => {
    log.info('No updates available.');
  });

  autoUpdater.on('download-progress', (progress) => {
    log.info(`Download progress: ${Math.round(progress.percent)}%`);
  });

  autoUpdater.on('update-downloaded', (info) => {
    log.info('Update downloaded:', info.version);
  });

  autoUpdater.on('error', (error) => {
    log.warn('Auto-updater error:', error.message);
  });

  // Check for updates after a short delay (don't block startup)
  setTimeout(() => {
    autoUpdater.checkForUpdates().catch(err => {
      log.warn('Update check failed:', err.message);
    });
  }, 5000);
}

module.exports = { setupUpdater };

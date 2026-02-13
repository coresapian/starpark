/**
 * LinkSpot Electron - Settings Window Logic
 */

const backendInput = document.getElementById('backend-url');
const testBtn = document.getElementById('test-btn');
const testStatus = document.getElementById('test-status');
const notificationsToggle = document.getElementById('notifications-toggle');
const saveBtn = document.getElementById('save-btn');
const cancelBtn = document.getElementById('cancel-btn');

// Load current settings on open
window.addEventListener('DOMContentLoaded', async () => {
  const settings = await window.electronAPI.getSettings();
  backendInput.value = settings.backendURL || '';
  notificationsToggle.checked = settings.notifications !== false;
});

// Test connection
testBtn.addEventListener('click', async () => {
  const url = backendInput.value.trim().replace(/\/+$/, '');
  if (!url) {
    testStatus.textContent = 'Please enter a URL';
    testStatus.className = 'test-status error';
    return;
  }

  testStatus.textContent = 'Testing…';
  testStatus.className = 'test-status loading';
  testBtn.disabled = true;

  try {
    const result = await window.electronAPI.testBackend(url);
    if (result.success) {
      testStatus.textContent = `Connected (${result.status})`;
      testStatus.className = 'test-status success';
    } else {
      testStatus.textContent = `Failed: ${result.error}`;
      testStatus.className = 'test-status error';
    }
  } catch (err) {
    testStatus.textContent = `Error: ${err.message}`;
    testStatus.className = 'test-status error';
  } finally {
    testBtn.disabled = false;
  }
});

// Save settings
saveBtn.addEventListener('click', async () => {
  const url = backendInput.value.trim().replace(/\/+$/, '');

  await window.electronAPI.setSettings({
    backendURL: url || 'http://localhost:8000',
    notifications: notificationsToggle.checked
  });

  window.close();
});

// Cancel — close without saving
cancelBtn.addEventListener('click', () => {
  window.close();
});

// Enter key in URL input triggers test
backendInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    testBtn.click();
  }
});

// Escape key closes window
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    window.close();
  }
});

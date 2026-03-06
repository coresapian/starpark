/**
 * LinkSpot Electron - Settings Window Logic
 */

const backendInput = document.getElementById('backend-url');
const testBtn = document.getElementById('test-btn');
const testStatus = document.getElementById('test-status');
const notificationsToggle = document.getElementById('notifications-toggle');
const autoStartBackendToggle = document.getElementById('autostart-backend-toggle');
const saveBtn = document.getElementById('save-btn');
const cancelBtn = document.getElementById('cancel-btn');
let isDirty = false;

function normalizeBackendURL(rawValue) {
  const value = String(rawValue || '').trim().replace(/\/+$/, '');
  if (!value) return 'http://localhost:8000';
  const parsed = new URL(value);
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error('Backend URL must use HTTP or HTTPS');
  }
  return parsed.toString().replace(/\/$/, '');
}

// Load current settings on open
window.addEventListener('DOMContentLoaded', async () => {
  if (!window.electronAPI) {
    testStatus.textContent = 'Electron bridge unavailable';
    testStatus.className = 'test-status error';
    saveBtn.disabled = true;
    testBtn.disabled = true;
    return;
  }
  const settings = await window.electronAPI.getSettings();
  backendInput.value = settings.backendURL || '';
  notificationsToggle.checked = settings.notifications !== false;
  autoStartBackendToggle.checked = settings.autoStartLocalBackend !== false;
});

// Test connection
testBtn.addEventListener('click', async () => {
  let url;
  try {
    url = normalizeBackendURL(backendInput.value);
  } catch (error) {
    testStatus.textContent = error.message;
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
  let url;
  try {
    url = normalizeBackendURL(backendInput.value);
  } catch (error) {
    testStatus.textContent = error.message;
    testStatus.className = 'test-status error';
    return;
  }
  await window.electronAPI.setSettings({
    backendURL: url,
    notifications: notificationsToggle.checked,
    autoStartLocalBackend: autoStartBackendToggle.checked
  });

  isDirty = false;
  window.close();
});

// Cancel — close without saving
cancelBtn.addEventListener('click', () => {
  if (isDirty && !window.confirm('Discard unsaved changes?')) {
    return;
  }
  window.close();
});

backendInput.addEventListener('input', () => { isDirty = true; });
notificationsToggle.addEventListener('change', () => { isDirty = true; });
autoStartBackendToggle.addEventListener('change', () => { isDirty = true; });

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

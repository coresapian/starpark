import type { DesktopSettings } from "./contracts";

const backendInput = document.getElementById("backend-url") as HTMLInputElement | null;
const testButton = document.getElementById("test-btn") as HTMLButtonElement | null;
const testStatus = document.getElementById("test-status") as HTMLDivElement | null;
const notificationsToggle = document.getElementById("notifications-toggle") as HTMLInputElement | null;
const autoStartBackendToggle = document.getElementById("autostart-backend-toggle") as HTMLInputElement | null;
const saveButton = document.getElementById("save-btn") as HTMLButtonElement | null;
const cancelButton = document.getElementById("cancel-btn") as HTMLButtonElement | null;

let isDirty = false;

function setStatus(kind: "success" | "error" | "loading", message: string): void {
  if (!testStatus) {
    return;
  }
  testStatus.textContent = message;
  testStatus.className = `test-status ${kind}`;
}

function normalizeBackendUrl(rawValue: string): string {
  const value = String(rawValue || "").trim().replace(/\/+$/, "");
  if (!value) {
    return "http://localhost:8000";
  }
  const parsed = new URL(value);
  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new Error("Backend URL must use HTTP or HTTPS");
  }
  return parsed.toString().replace(/\/$/, "");
}

function readFormSettings(): DesktopSettings {
  if (!backendInput || !notificationsToggle || !autoStartBackendToggle) {
    throw new Error("Settings UI is not fully mounted");
  }
  return {
    backendURL: normalizeBackendUrl(backendInput.value),
    notifications: notificationsToggle.checked,
    autoStartLocalBackend: autoStartBackendToggle.checked
  };
}

async function loadSettings(): Promise<void> {
  if (!window.electronAPI) {
    setStatus("error", "Electron bridge unavailable");
    if (saveButton) saveButton.disabled = true;
    if (testButton) testButton.disabled = true;
    return;
  }

  const settings = await window.electronAPI.getSettings();
  if (backendInput) backendInput.value = settings.backendURL ?? "";
  if (notificationsToggle) notificationsToggle.checked = settings.notifications !== false;
  if (autoStartBackendToggle) autoStartBackendToggle.checked = settings.autoStartLocalBackend !== false;
}

async function testConnection(): Promise<void> {
  if (!window.electronAPI || !testButton || !backendInput) {
    return;
  }

  let url: string;
  try {
    url = normalizeBackendUrl(backendInput.value);
  } catch (error) {
    setStatus("error", error instanceof Error ? error.message : "Invalid backend URL");
    return;
  }

  setStatus("loading", "Testing...");
  testButton.disabled = true;

  try {
    const result = await window.electronAPI.testBackend(url);
    if (result.success) {
      setStatus("success", `Connected (${result.status ?? "ok"})`);
    } else {
      setStatus("error", `Failed: ${result.error ?? "Unknown backend error"}`);
    }
  } catch (error) {
    setStatus("error", error instanceof Error ? error.message : "Backend test failed");
  } finally {
    testButton.disabled = false;
  }
}

async function saveSettings(): Promise<void> {
  if (!window.electronAPI) {
    return;
  }

  const result = await window.electronAPI.setSettings(readFormSettings());
  if (!result.success) {
    setStatus("error", result.error ?? "Could not save settings");
    return;
  }

  isDirty = false;
  window.close();
}

function confirmClose(): void {
  if (isDirty && !window.confirm("Discard unsaved changes?")) {
    return;
  }
  window.close();
}

window.addEventListener("DOMContentLoaded", () => {
  void loadSettings();
});

backendInput?.addEventListener("input", () => {
  isDirty = true;
});
notificationsToggle?.addEventListener("change", () => {
  isDirty = true;
});
autoStartBackendToggle?.addEventListener("change", () => {
  isDirty = true;
});
testButton?.addEventListener("click", () => {
  void testConnection();
});
saveButton?.addEventListener("click", () => {
  void saveSettings();
});
cancelButton?.addEventListener("click", () => {
  confirmClose();
});
backendInput?.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    void testConnection();
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    confirmClose();
  }
});

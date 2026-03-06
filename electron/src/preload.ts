import { contextBridge, ipcRenderer } from "electron";

import type {
  BackendBootstrapStatus,
  BackendStatusPayload,
  DesktopSettings,
  ElectronBridge,
  NotificationPayload
} from "./contracts";

type IpcListener<T> = (payload: T) => void;

function registerListener<T>(
  channel: string,
  callback: IpcListener<T>,
  mapper: (...args: unknown[]) => T
): () => void {
  const handler = (...args: unknown[]) => callback(mapper(...args));
  ipcRenderer.on(channel, handler);
  return () => ipcRenderer.removeListener(channel, handler);
}

const bridge: ElectronBridge = {
  platform: process.platform,
  isElectron: true,
  getSettings: () => ipcRenderer.invoke("get-settings") as Promise<DesktopSettings>,
  setSettings: (settings) =>
    ipcRenderer.invoke("set-settings", settings) as Promise<{ success: boolean; error?: string }>,
  testBackend: (url) => ipcRenderer.invoke("test-backend", url),
  startLocalBackend: () => ipcRenderer.invoke("start-local-backend"),
  promptLocationPermission: () => ipcRenderer.invoke("prompt-location-permission"),
  showNotification: (payload: NotificationPayload) =>
    ipcRenderer.invoke("show-notification", payload),
  onFocusSearch: (callback) => registerListener("focus-search", callback, () => undefined),
  onRefreshMap: (callback) => registerListener("refresh-map", callback, () => undefined),
  onGoToLocation: (callback) => registerListener("go-to-location", callback, () => undefined),
  onSettingsChanged: (callback) =>
    registerListener("settings-changed", callback, (_event, payload) => payload as DesktopSettings),
  onBackendStatus: (callback) =>
    registerListener("backend-status", callback, (_event, payload) => {
      const raw = (payload ?? {}) as Partial<BackendStatusPayload>;
      return {
        connected: Boolean(raw.connected),
        overall: String(raw.overall ?? "unknown"),
        components: Array.isArray(raw.components) ? raw.components : []
      } satisfies BackendStatusPayload;
    }),
  onBackendBootstrapStatus: (callback) =>
    registerListener("backend-bootstrap-status", callback, (_event, payload) => {
      const raw = (payload ?? {}) as Partial<BackendBootstrapStatus>;
      return {
        phase: String(raw.phase ?? "unknown"),
        message: String(raw.message ?? ""),
        timestamp: Number(raw.timestamp ?? Date.now())
      } satisfies BackendBootstrapStatus;
    })
};

contextBridge.exposeInMainWorld("electronAPI", bridge);

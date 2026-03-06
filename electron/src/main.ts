import { execSync } from "child_process";
import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  net,
  Notification,
  session,
  shell,
  type WebContents
} from "electron";
import fs from "fs";
import path from "path";

import type { BackendStatusPayload, DesktopSettings, NotificationPayload } from "./contracts";

interface LogTransport {
  level: string;
}

interface ElectronLogLike {
  transports: {
    file: LogTransport;
    console: LogTransport;
  };
  info: (...args: unknown[]) => void;
  warn: (...args: unknown[]) => void;
  error: (...args: unknown[]) => void;
}

interface WindowStateKeeperLike {
  x?: number;
  y?: number;
  width: number;
  height: number;
  manage(window: BrowserWindow): void;
}

interface WindowStateKeeperFactory {
  (options: { defaultWidth: number; defaultHeight: number }): WindowStateKeeperLike;
}

interface StoreFacade {
  get(key: string): unknown;
  set(key: string, value: unknown): void;
  normalizeBackendURL(rawValue: string): string;
  normalizeSettingsPatch(settings: Partial<DesktopSettings>): Partial<DesktopSettings>;
}

interface LocalBackendStatus {
  phase: string;
  message: string;
  timestamp: number;
}

interface LocalBackendManager {
  start(options: { trigger: string }): Promise<{ success: boolean; error?: string }>;
  autoStartIfEnabled(): Promise<void>;
}

interface CreateLocalBackendManager {
  (options: {
    app: typeof app;
    net: typeof net;
    shell: typeof shell;
    log: ElectronLogLike;
    store: StoreFacade;
    onStatus: (status: LocalBackendStatus) => void;
  }): LocalBackendManager;
}

type CreateMenu = (options: {
  onPreferences: () => void;
  getMainWindow: () => BrowserWindow | null;
}) => void;

type CreateTray = (options: {
  onShow: () => void;
  onPreferences: () => void;
  getMainWindow: () => BrowserWindow | null;
}) => void;

type DestroyTray = () => void;

type SetupUpdater = (options: { enabled: boolean }) => void;

const log = require("electron-log") as ElectronLogLike;
const windowStateKeeper = require("electron-window-state") as WindowStateKeeperFactory;
const { registerScheme, setupProtocolHandler } = require("../protocol-handler") as {
  registerScheme: () => void;
  setupProtocolHandler: () => void;
};
const store = require("../store") as StoreFacade;
const { createMenu } = require("../menu") as { createMenu: CreateMenu };
const { createTray, destroyTray } = require("../tray") as {
  createTray: CreateTray;
  destroyTray: DestroyTray;
};
const { setupUpdater } = require("../updater") as { setupUpdater: SetupUpdater };
const { createLocalBackendManager } = require("../local-backend") as {
  createLocalBackendManager: CreateLocalBackendManager;
};

log.transports.file.level = "info";
log.transports.console.level = "debug";

registerScheme();

let mainWindow: BrowserWindow | null = null;
let settingsWindow: BrowserWindow | null = null;
let backendPollIntervalId: ReturnType<typeof setInterval> | null = null;
let localBackendManager: LocalBackendManager | null = null;

function resolvePreloadPath(): string {
  const emittedPath = path.join(__dirname, "preload.js");
  if (fs.existsSync(emittedPath)) {
    return emittedPath;
  }
  return path.join(__dirname, "..", "preload.js");
}

function isTrustedRenderer(webContents: WebContents): boolean {
  try {
    const currentUrl = new URL(webContents.getURL());
    return currentUrl.protocol === "app:" && currentUrl.host === "linkspot";
  } catch {
    return false;
  }
}

function getDesktopSettings(): DesktopSettings {
  return {
    backendURL: String(store.get("backendURL") ?? ""),
    notifications: store.get("notifications") !== false,
    autoStartLocalBackend: store.get("autoStartLocalBackend") !== false
  };
}

function normalizeBackendStatusPayload(payload: unknown, connected: boolean): BackendStatusPayload {
  const raw = (payload ?? {}) as {
    status?: unknown;
    components?: Array<{ name?: unknown; status?: unknown; message?: unknown }>;
  };
  return {
    connected,
    overall: String(raw.status ?? (connected ? "unknown" : "unreachable")),
    components: Array.isArray(raw.components)
      ? raw.components.map((component) => ({
          name: String(component?.name ?? "unknown"),
          status: String(component?.status ?? "unknown"),
          message:
            component?.message === undefined ? undefined : String(component.message),
        }))
      : [],
  };
}

function createMainWindow(): BrowserWindow {
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
    title: "LinkSpot",
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 16, y: 16 },
    backgroundColor: "#1a1a2e",
    webPreferences: {
      preload: resolvePreloadPath(),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });

  mainWindowState.manage(mainWindow);

  void mainWindow.loadURL("app://linkspot/").catch((error: unknown) => {
    log.error("Failed to load app:// URL:", error);
  });

  mainWindow.webContents.on(
    "did-fail-load",
    (_event, errorCode, errorDescription) => {
      log.error("Renderer load failed:", errorCode, errorDescription);
    }
  );

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  return mainWindow;
}

function createSettingsWindow(): void {
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
    title: "Preferences",
    backgroundColor: "#1a1a2e",
    parent: mainWindow ?? undefined,
    modal: false,
    show: false,
    webPreferences: {
      preload: resolvePreloadPath(),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });

  void settingsWindow.loadFile(path.join(__dirname, "..", "settings.html"));

  settingsWindow.once("ready-to-show", () => {
    settingsWindow?.show();
  });

  settingsWindow.on("closed", () => {
    settingsWindow = null;
  });
}

ipcMain.handle("get-settings", () => getDesktopSettings());

ipcMain.handle("set-settings", (_event, settings: Partial<DesktopSettings>) => {
  try {
    const normalized = store.normalizeSettingsPatch(settings);
    Object.entries(normalized).forEach(([key, value]) => store.set(key, value));
  } catch (error) {
    const message = error instanceof Error ? error.message : "Invalid settings payload";
    return { success: false, error: message };
  }

  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("settings-changed", getDesktopSettings());
  }

  return { success: true };
});

ipcMain.handle("test-backend", async (_event, url: string) => {
  try {
    const normalized = store.normalizeBackendURL(url);
    const response = await net.fetch(`${normalized}/api/v1/health`, { method: "GET" });
    const data = (await response.json()) as { status?: unknown };
    return { success: true, status: String(data.status ?? "connected") };
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : "Backend test failed"
    };
  }
});

ipcMain.handle("prompt-location-permission", async () => {
  const messageBoxOptions = {
    type: "info" as const,
    title: "Location Access Required",
    message:
      "LinkSpot needs access to your location to center the map and analyze satellite visibility.",
    detail:
      "Please enable Location Services for LinkSpot in System Settings > Privacy & Security > Location Services.",
    buttons: ["Open System Settings", "Cancel"],
    defaultId: 0,
    cancelId: 1
  };
  const { response } = mainWindow
    ? await dialog.showMessageBox(mainWindow, messageBoxOptions)
    : await dialog.showMessageBox(messageBoxOptions);

  if (response === 0) {
    await shell.openExternal(
      "x-apple.systempreferences:com.apple.preference.security?Privacy_LocationServices"
    );
  }

  return { opened: response === 0 };
});

ipcMain.handle("show-notification", (_event, opts: NotificationPayload) => {
  if (store.get("notifications") === false) {
    return { shown: false };
  }

  const notification = new Notification({
    title: opts.title || "LinkSpot",
    body: opts.body || "",
    silent: opts.silent || false
  });
  notification.show();
  return { shown: true };
});

ipcMain.handle("start-local-backend", async () => {
  if (!localBackendManager) {
    return { success: false, error: "Local backend manager is unavailable." };
  }
  return localBackendManager.start({ trigger: "manual" });
});

function patchDevInfoPlist(): void {
  if (app.isPackaged) {
    return;
  }

  try {
    const plistPath = path.join(path.dirname(process.execPath), "..", "Info.plist");
    if (!fs.existsSync(plistPath)) {
      return;
    }
    const content = fs.readFileSync(plistPath, "utf-8");
    if (content.includes("NSLocationUsageDescription")) {
      return;
    }
    execSync(
      `/usr/libexec/PlistBuddy -c "Add :NSLocationUsageDescription string 'LinkSpot needs your location to center the map and analyze satellite visibility.'" "${plistPath}"`,
      { stdio: "ignore" }
    );
    log.info("Patched dev Electron.app Info.plist with NSLocationUsageDescription");
  } catch (error) {
    log.warn(
      "Could not patch dev Info.plist:",
      error instanceof Error ? error.message : error
    );
  }
}

async function checkBackend(): Promise<BackendStatusPayload> {
  const backendUrl = String(store.get("backendURL") ?? "");
  try {
    const response = await net.fetch(`${backendUrl}/api/v1/health/detailed`, {
      method: "GET"
    });
    const payload = await response.json().catch(() => ({}));
    return normalizeBackendStatusPayload(payload, response.ok);
  } catch {
    return {
      connected: false,
      overall: "unreachable",
      components: []
    };
  }
}

async function bootstrapApplication(): Promise<void> {
  log.info("LinkSpot Electron starting...");

  patchDevInfoPlist();
  setupProtocolHandler();

  const allowedPermissions = ["geolocation", "notifications", "media"];
  session.defaultSession.setPermissionRequestHandler(
    (webContents, permission, callback) => {
      callback(
        isTrustedRenderer(webContents) && allowedPermissions.includes(permission)
      );
    }
  );
  session.defaultSession.setPermissionCheckHandler((webContents, permission) => {
    return (
      webContents !== null &&
      isTrustedRenderer(webContents) &&
      allowedPermissions.includes(permission)
    );
  });

  createMainWindow();

  localBackendManager = createLocalBackendManager({
    app,
    net,
    shell,
    log,
    store,
    onStatus: (status) => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send("backend-bootstrap-status", status);
      }
    }
  });

  void localBackendManager.autoStartIfEnabled().catch((error: unknown) => {
    log.warn(
      "Auto-start local backend failed:",
      error instanceof Error ? error.message : error
    );
  });

  createMenu({
    onPreferences: createSettingsWindow,
    getMainWindow: () => mainWindow
  });

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

  setupUpdater({
    enabled: app.isPackaged && store.get("autoUpdateEnabled") !== false
  });

  let lastBackendStatus: BackendStatusPayload | null = null;
  const publishBackendStatus = async (): Promise<void> => {
    const status = await checkBackend();
    if (JSON.stringify(status) === JSON.stringify(lastBackendStatus)) {
      return;
    }
    lastBackendStatus = status;
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send("backend-status", status);
    }
  };

  await publishBackendStatus();
  backendPollIntervalId = setInterval(() => {
    void publishBackendStatus();
  }, 30000);

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow();
    } else if (mainWindow) {
      mainWindow.show();
    }
  });
}

void app.whenReady().then(bootstrapApplication);

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  destroyTray();
  if (backendPollIntervalId) {
    clearInterval(backendPollIntervalId);
    backendPollIntervalId = null;
  }
  localBackendManager = null;
});

export { createSettingsWindow };

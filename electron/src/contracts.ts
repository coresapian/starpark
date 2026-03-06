export interface DesktopSettings {
  backendURL: string;
  notifications: boolean;
  autoStartLocalBackend: boolean;
}

export interface BackendTestResult {
  success: boolean;
  status?: string;
  error?: string;
}

export interface NotificationPayload {
  title?: string;
  body?: string;
  silent?: boolean;
}

export interface BackendComponentStatus {
  name: string;
  status: string;
  message?: string;
}

export interface BackendStatusPayload {
  connected: boolean;
  overall: string;
  components: BackendComponentStatus[];
}

export interface BackendBootstrapStatus {
  phase: string;
  message: string;
  timestamp: number;
}

export interface ElectronBridge {
  platform: string;
  isElectron: boolean;
  getSettings(): Promise<DesktopSettings>;
  setSettings(settings: Partial<DesktopSettings>): Promise<{ success: boolean; error?: string }>;
  testBackend(url: string): Promise<BackendTestResult>;
  startLocalBackend(): Promise<{ success: boolean; error?: string }>;
  promptLocationPermission(): Promise<{ opened: boolean }>;
  showNotification(payload: NotificationPayload): Promise<{ shown: boolean }>;
  onFocusSearch(callback: () => void): () => void;
  onRefreshMap(callback: () => void): () => void;
  onGoToLocation(callback: () => void): () => void;
  onSettingsChanged(callback: (settings: DesktopSettings) => void): () => void;
  onBackendStatus(callback: (status: BackendStatusPayload) => void): () => void;
  onBackendBootstrapStatus(callback: (payload: BackendBootstrapStatus) => void): () => void;
}

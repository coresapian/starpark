import type { ElectronBridge } from "../../../../shared/contracts/electron";

declare global {
  interface Window {
    electronAPI?: ElectronBridge;
  }
}

export {};

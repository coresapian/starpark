import { useEffect, useState } from "react";

import { BackendClient, type DetailedHealthResponse, type HealthStatus } from "../lib/api";
import type { BackendBootstrapStatus, BackendStatusPayload } from "../../../../shared/contracts/electron";

interface HealthState {
  data: DetailedHealthResponse | null;
  loading: boolean;
  error: string | null;
}

const client = new BackendClient();

function normalizeStatus(status: string | undefined): HealthStatus {
  if (status === "healthy" || status === "degraded" || status === "unhealthy") {
    return status;
  }
  return "unknown";
}

function mapElectronStatus(status: BackendStatusPayload): DetailedHealthResponse {
  return {
    status: status.connected ? normalizeStatus(status.overall) : "unhealthy",
    components: status.components.map((component: BackendStatusPayload["components"][number]) => ({
      name: component.name,
      status: normalizeStatus(component.status),
      message: component.message
    })),
    timestamp: new Date().toISOString()
  };
}

function mapBootstrapError(payload: BackendBootstrapStatus): string | null {
  const phase = String(payload.phase || "").toLowerCase();
  if (phase.includes("fail") || phase.includes("error")) {
    return payload.message || "Desktop backend bootstrap failed";
  }
  return null;
}

export function useBackendHealth(): HealthState {
  const [state, setState] = useState<HealthState>({
    data: null,
    loading: true,
    error: null
  });

  useEffect(() => {
    let cancelled = false;
    const electronAPI = window.electronAPI;
    let unsubscribeStatus: (() => void) | undefined;
    let unsubscribeBootstrap: (() => void) | undefined;

    async function load(): Promise<void> {
      try {
        const data = await client.getDetailedHealth();
        if (cancelled) {
          return;
        }
        setState({ data, loading: false, error: null });
      } catch (error) {
        if (cancelled) {
          return;
        }
        setState({
          data: null,
          loading: false,
          error: error instanceof Error ? error.message : "Unknown backend failure"
        });
      }
    }

    if (electronAPI?.isElectron) {
      unsubscribeStatus = electronAPI.onBackendStatus((status) => {
        if (cancelled) {
          return;
        }
        setState({ data: mapElectronStatus(status), loading: false, error: null });
      });
      unsubscribeBootstrap = electronAPI.onBackendBootstrapStatus((payload) => {
        if (cancelled) {
          return;
        }
        const message = mapBootstrapError(payload);
        if (!message) {
          return;
        }
        setState((current) => ({
          data: current.data,
          loading: false,
          error: message
        }));
      });
    }

    load().catch(() => undefined);
    const timer = window.setInterval(load, 30000);
    return () => {
      cancelled = true;
      unsubscribeStatus?.();
      unsubscribeBootstrap?.();
      window.clearInterval(timer);
    };
  }, []);

  return state;
}

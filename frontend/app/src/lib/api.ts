export type HealthStatus = "healthy" | "degraded" | "unhealthy" | "unknown";

export interface ComponentHealth {
  name: string;
  status: HealthStatus;
  message?: string;
}

export interface DetailedHealthResponse {
  status: HealthStatus;
  components: ComponentHealth[];
  timestamp?: string;
}

export interface AnalyzeRequest {
  lat: number;
  lon: number;
  elevation?: number;
}

export interface AnalyzeResponse {
  zone: string;
  n_clear: number;
  n_total: number;
  obstruction_pct: number;
}

export class BackendClient {
  constructor(private readonly baseUrl: string = "/api/v1") {}

  async getDetailedHealth(): Promise<DetailedHealthResponse> {
    const response = await fetch(`${this.baseUrl}/health/detailed`, {
      headers: {
        Accept: "application/json"
      }
    });
    if (!response.ok) {
      throw new Error(`Health request failed: ${response.status}`);
    }
    return response.json() as Promise<DetailedHealthResponse>;
  }

  async analyze(request: AnalyzeRequest): Promise<AnalyzeResponse> {
    const response = await fetch(`${this.baseUrl}/analyze`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json"
      },
      body: JSON.stringify(request)
    });
    if (!response.ok) {
      throw new Error(`Analyze request failed: ${response.status}`);
    }
    return response.json() as Promise<AnalyzeResponse>;
  }
}

export type HealthStatus = "healthy" | "degraded" | "unhealthy" | "unknown";
export type CoverageZone = "excellent" | "good" | "fair" | "poor" | "blocked";

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
  timestamp?: string;
}

export interface VisibilitySummary {
  visible_satellites: number;
  obstructed_satellites: number;
  total_satellites: number;
}

export interface SatelliteDetail {
  id: string;
  name: string;
  azimuth: number;
  elevation: number;
  range_km?: number;
  visible: boolean;
  obstructed: boolean;
  snr?: number;
}

export interface ObstructionPoint {
  azimuth: number;
  elevation: number;
}

export interface DataQuality {
  buildings: string;
  terrain: string;
  satellites: string;
  sources: string[];
  warnings: string[];
}

export interface AnalyzeResponse {
  zone: CoverageZone;
  n_clear: number;
  n_total: number;
  obstruction_pct: number;
  blocked_azimuths: number[];
  timestamp: string;
  lat: number;
  lon: number;
  elevation: number;
  visibility?: VisibilitySummary;
  satellites: SatelliteDetail[];
  obstructions: ObstructionPoint[];
  data_quality?: DataQuality;
}

export interface GeoJsonGeometry {
  type: "Point" | "LineString" | "Polygon" | "MultiPolygon" | "MultiLineString";
  coordinates: unknown;
}

export interface GeoJsonFeature {
  type: "Feature";
  geometry: GeoJsonGeometry;
  properties: Record<string, unknown>;
  id?: string | number;
}

export interface GeoJsonFeatureCollection {
  type: "FeatureCollection";
  features: GeoJsonFeature[];
}

export interface RouteLocationInput {
  lat?: number;
  lon?: number;
  address?: string;
}

export interface WaypointAmenities {
  parking: boolean;
  restroom: boolean;
  fuel: boolean;
  food: boolean;
}

export interface Waypoint {
  id: string;
  lat: number;
  lon: number;
  name: string;
  type: string;
  coverage_pct: number;
  visible_satellites: number;
  total_satellites: number;
  zone: CoverageZone;
  distance_from_origin_m: number;
  eta_seconds: number;
  distance_to_next_m?: number;
  max_obstruction_deg?: number;
  amenities: WaypointAmenities;
  best_window?: string;
}

export interface DeadZone {
  start_distance_m: number;
  end_distance_m: number;
  length_m: number;
  start_lat: number;
  start_lon: number;
  end_lat: number;
  end_lon: number;
}

export interface MissionSummary {
  origin_name?: string;
  destination_name?: string;
  total_distance_m: number;
  total_duration_s: number;
  num_waypoints: number;
  max_gap_m: number;
  num_dead_zones: number;
  dead_zone_total_m: number;
  route_coverage_pct: number;
}

export interface RoutePlanResponse {
  route_geojson: GeoJsonFeatureCollection;
  waypoints: Waypoint[];
  dead_zones: DeadZone[];
  mission_summary: MissionSummary;
  data_quality?: DataQuality;
  signal_forecast: string[];
}

export function formatClientError(error: unknown, fallbackMessage: string): string {
  const message =
    error instanceof Error && error.message.trim()
      ? error.message.trim()
      : fallbackMessage;

  if (/request timed out/i.test(message)) {
    return "The request took too long. Please try again.";
  }

  if (
    /failed to fetch/i.test(message) ||
    /networkerror/i.test(message) ||
    /^(404|500|502|503|504)\b/.test(message)
  ) {
    return "LinkSpot services are not reachable right now.";
  }

  return message;
}

export class BackendClient {
  constructor(private readonly baseUrl: string = "/api/v1") {}

  private async request<T>(
    path: string,
    init: RequestInit = {},
    timeoutMs: number = 30000
  ): Promise<T> {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    const externalSignal = init.signal;

    const abortFromExternalSignal = (): void => controller.abort();
    if (externalSignal) {
      if (externalSignal.aborted) {
        controller.abort();
      } else {
        externalSignal.addEventListener("abort", abortFromExternalSignal, {
          once: true
        });
      }
    }

    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        signal: controller.signal,
        headers: {
          Accept: "application/json",
          ...(init.body ? { "Content-Type": "application/json" } : {}),
          ...init.headers
        }
      });

      if (!response.ok) {
        let message = `${response.status} ${response.statusText}`;
        try {
          const errorPayload = (await response.json()) as {
            detail?: string;
            message?: string;
            error?: string;
          };
          message =
            errorPayload.detail ||
            errorPayload.message ||
            errorPayload.error ||
            message;
        } catch {
          const text = await response.text().catch(() => "");
          if (text) {
            message = text;
          }
        }
        throw new Error(message);
      }

      return (await response.json()) as T;
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        throw new Error("Request timed out");
      }
      throw error;
    } finally {
      window.clearTimeout(timer);
      externalSignal?.removeEventListener("abort", abortFromExternalSignal);
    }
  }

  async getDetailedHealth(): Promise<DetailedHealthResponse> {
    return this.request<DetailedHealthResponse>("/health/detailed");
  }

  async analyze(request: AnalyzeRequest): Promise<AnalyzeResponse> {
    return this.request<AnalyzeResponse>(
      "/analyze",
      {
        method: "POST",
        body: JSON.stringify(request)
      },
      45000
    );
  }

  async planRoute(
    origin: RouteLocationInput,
    destination: RouteLocationInput,
    sampleIntervalMeters: number,
    timeUtc?: string
  ): Promise<RoutePlanResponse> {
    return this.request<RoutePlanResponse>(
      "/route/plan",
      {
        method: "POST",
        body: JSON.stringify({
          origin,
          destination,
          sample_interval_m: sampleIntervalMeters,
          ...(timeUtc ? { time_utc: timeUtc } : {})
        })
      },
      120000
    );
  }
}

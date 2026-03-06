import { useMemo, useState } from "react";

import { MissionMap } from "./components/MissionMap";
import { useBackendHealth } from "./hooks/useBackendHealth";
import {
  BackendClient,
  type AnalyzeResponse,
  type RouteLocationInput,
  type RoutePlanResponse,
  type SatelliteDetail,
  formatClientError
} from "./lib/api";

const client = new BackendClient();

interface TargetPoint {
  lat: number;
  lon: number;
}

function ledClass(status: string | undefined): string {
  if (status === "healthy") return "led led-green";
  if (status === "degraded") return "led led-amber";
  if (status === "unhealthy") return "led led-red";
  return "led led-muted";
}

function parseCoordinateValue(value: string): number | null {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseTargetPoint(latValue: string, lonValue: string): TargetPoint | null {
  const lat = parseCoordinateValue(latValue);
  const lon = parseCoordinateValue(lonValue);
  if (lat === null || lon === null) {
    return null;
  }
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) {
    return null;
  }
  return { lat, lon };
}

function parseRouteLocation(
  rawValue: string,
  fallbackTarget?: TargetPoint | null
): RouteLocationInput | null {
  const trimmed = rawValue.trim();
  if (!trimmed) {
    return fallbackTarget ?? null;
  }

  const maybeCoordinates = trimmed.split(",").map((part) => part.trim());
  if (maybeCoordinates.length === 2) {
    const lat = Number.parseFloat(maybeCoordinates[0]);
    const lon = Number.parseFloat(maybeCoordinates[1]);
    if (Number.isFinite(lat) && Number.isFinite(lon)) {
      return { lat, lon };
    }
  }

  return { address: trimmed };
}

function formatDistance(distanceMeters: number | undefined): string {
  if (!distanceMeters || distanceMeters <= 0) {
    return "--";
  }
  if (distanceMeters >= 1000) {
    return `${(distanceMeters / 1000).toFixed(1)} km`;
  }
  return `${Math.round(distanceMeters)} m`;
}

function formatDuration(durationSeconds: number | undefined): string {
  if (!durationSeconds || durationSeconds <= 0) {
    return "--";
  }
  const totalMinutes = Math.round(durationSeconds / 60);
  if (totalMinutes >= 60) {
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    return `${hours}h ${minutes}m`;
  }
  return `${totalMinutes} min`;
}

function formatSignalLabel(signal: string): string {
  return signal.charAt(0).toUpperCase() + signal.slice(1);
}

function formatZoneLabel(zone: string | undefined): string {
  if (!zone) {
    return "--";
  }
  return zone.charAt(0).toUpperCase() + zone.slice(1);
}

function formatOverallStatus(status: string | undefined): string {
  if (status === "healthy") {
    return "Online";
  }
  if (status === "degraded") {
    return "Limited";
  }
  if (status === "unhealthy") {
    return "Offline";
  }
  return "Checking";
}

function formatCoverageNote(note: string): string {
  if (/no building data available/i.test(note)) {
    return "Building data is unavailable here, so visibility estimates may be less precise.";
  }
  if (/terrain elevation data unavailable/i.test(note)) {
    return "Terrain data is unavailable here, so obstruction estimates may be less precise.";
  }
  if (/amenities unavailable/i.test(note)) {
    return "Nearby stop amenities could not be loaded for this route.";
  }
  if (/no parking\/fuel\/rest candidates fell inside the drivable route corridor/i.test(note)) {
    return "No nearby stops were found directly along this route.";
  }
  if (/no parking\/fuel\/rest locations met connectivity criteria/i.test(note)) {
    return "No suggested stops met the coverage threshold on this route.";
  }
  if (/route analysis budget exhausted/i.test(note)) {
    return "The route check ended before every sample could be processed.";
  }
  if (/waypoint candidate analysis stopped/i.test(note)) {
    return "Stop analysis ended before every candidate could be checked.";
  }
  if (/sample point\(s\) failed and were marked as blocked/i.test(note)) {
    return "Some route samples could not be checked and were treated as blocked areas.";
  }
  return note.replace(/^\[[^\]]+\]\s*/, "");
}

function sortSatellites(satellites: SatelliteDetail[]): SatelliteDetail[] {
  return [...satellites].sort((left, right) => right.elevation - left.elevation);
}

export function App(): JSX.Element {
  const [targetLat, setTargetLat] = useState("39.7392");
  const [targetLon, setTargetLon] = useState("-104.9903");
  const [origin, setOrigin] = useState("");
  const [destination, setDestination] = useState("Boulder, CO");
  const [sampleInterval, setSampleInterval] = useState("750");
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [routePlan, setRoutePlan] = useState<RoutePlanResponse | null>(null);
  const [routeLoading, setRouteLoading] = useState(false);
  const [routeError, setRouteError] = useState<string | null>(null);
  const health = useBackendHealth();
  const targetPoint = useMemo(
    () => parseTargetPoint(targetLat, targetLon),
    [targetLat, targetLon]
  );
  const hasClassicView = !import.meta.env.DEV;

  const topSatellites = useMemo(
    () => sortSatellites(analysis?.satellites ?? []).slice(0, 6),
    [analysis]
  );

  const dataWarnings = useMemo(() => {
    const warnings = new Set<string>();
    for (const warning of analysis?.data_quality?.warnings ?? []) {
      warnings.add(formatCoverageNote(warning));
    }
    for (const warning of routePlan?.data_quality?.warnings ?? []) {
      warnings.add(formatCoverageNote(warning));
    }
    return [...warnings];
  }, [analysis, routePlan]);

  async function runAnalyze(): Promise<void> {
    setAnalysisError(null);
    if (!targetPoint) {
      setAnalysisError("Enter valid latitude and longitude values.");
      return;
    }

    setAnalysisLoading(true);
    try {
      const data = await client.analyze({
        lat: targetPoint.lat,
        lon: targetPoint.lon,
        elevation: 0
      });
      setAnalysis(data);
    } catch (error) {
      setAnalysisError(formatClientError(error, "Coverage check failed."));
    } finally {
      setAnalysisLoading(false);
    }
  }

  async function runRoutePlan(): Promise<void> {
    setRouteError(null);
    const interval = Number.parseFloat(sampleInterval);
    if (!Number.isFinite(interval) || interval < 100 || interval > 5000) {
      setRouteError("Sampling distance must be between 100 and 5000 meters.");
      return;
    }

    const parsedOrigin = parseRouteLocation(origin, targetPoint);
    const parsedDestination = parseRouteLocation(destination);
    if (!parsedOrigin) {
      setRouteError("Enter a start point or pick one on the map.");
      return;
    }
    if (!parsedDestination) {
      setRouteError("Enter an end point or a coordinate pair.");
      return;
    }

    setRouteLoading(true);
    try {
      const data = await client.planRoute(
        parsedOrigin,
        parsedDestination,
        interval
      );
      setRoutePlan(data);
    } catch (error) {
      setRouteError(formatClientError(error, "Route planning failed."));
    } finally {
      setRouteLoading(false);
    }
  }

  function assignTargetTo(field: "origin" | "destination"): void {
    if (!targetPoint) {
      return;
    }
    const nextValue = `${targetPoint.lat.toFixed(5)}, ${targetPoint.lon.toFixed(5)}`;
    if (field === "origin") {
      setOrigin(nextValue);
      return;
    }
    setDestination(nextValue);
  }

  function handleTargetSelect(nextTarget: TargetPoint): void {
    setTargetLat(nextTarget.lat.toFixed(5));
    setTargetLon(nextTarget.lon.toFixed(5));
  }

  function navigateToLegacyConsole(): void {
    window.location.assign("/legacy/");
  }

  const routeSummary = routePlan?.mission_summary;

  return (
    <div className="mission-shell">
      <header className="status-strip panel">
        <div className="status-left">
          <div className={ledClass(health.data?.status)} />
          <span className="status-title">LINKSPOT MISSION CONTROL</span>
        </div>
        <div className="status-right">
          <span className={ledClass(health.data?.status)} />
          <span>{formatOverallStatus(health.data?.status)}</span>
        </div>
      </header>

      <aside className="panel command-rail">
        <section className="panel-block">
          <div className="eyebrow">Coverage Check</div>
          <p className="panel-copy">
            Click the map or enter coordinates to check satellite visibility at a point.
          </p>
          <label>
            Latitude
            <input value={targetLat} onChange={(event) => setTargetLat(event.target.value)} />
          </label>
          <label>
            Longitude
            <input value={targetLon} onChange={(event) => setTargetLon(event.target.value)} />
          </label>
          <div className="action-row">
            <button className="accent-button" onClick={() => void runAnalyze()} disabled={analysisLoading}>
              {analysisLoading ? "Checking..." : "Check Coverage"}
            </button>
            <button className="ghost-button" onClick={() => assignTargetTo("origin")} disabled={!targetPoint}>
              Use as Start
            </button>
            <button
              className="ghost-button"
              onClick={() => assignTargetTo("destination")}
              disabled={!targetPoint}
            >
              Use as End
            </button>
          </div>
          {analysisError ? <p className="error-copy">{analysisError}</p> : null}
        </section>

        <section className="panel-block">
          <div className="eyebrow">Route Planner</div>
          <label>
            Start
            <input
              value={origin}
              onChange={(event) => setOrigin(event.target.value)}
              placeholder="Address or lat, lon"
            />
          </label>
          <label>
            End
            <input
              value={destination}
              onChange={(event) => setDestination(event.target.value)}
              placeholder="Address or lat, lon"
            />
          </label>
          <label>
            Sampling Distance (m)
            <input
              value={sampleInterval}
              onChange={(event) => setSampleInterval(event.target.value)}
            />
          </label>
          <div className="action-row">
            <button className="accent-button" onClick={() => void runRoutePlan()} disabled={routeLoading}>
              {routeLoading ? "Planning..." : "Plan Route"}
            </button>
            <button className="ghost-button" onClick={() => setRoutePlan(null)} disabled={!routePlan}>
              Clear Route
            </button>
          </div>
          {routeError ? <p className="error-copy">{routeError}</p> : null}
        </section>

      </aside>

      <main className="panel tactical-stage">
        <MissionMap
          target={targetPoint}
          analysis={analysis}
          routePlan={routePlan}
          onSelectTarget={handleTargetSelect}
        />
        <div className="map-intel-overlay">
          <p className="eyebrow">Map View</p>
          <h1>See coverage at a point or along a route.</h1>
          <p>
            Click any point on the map to inspect visibility, then compare coverage from start to
            end.
          </p>
          <div className="stat-cluster">
            <div className="stat-pill">
              <span className="stat-label">Coverage</span>
              <strong>{formatZoneLabel(analysis?.zone)}</strong>
            </div>
            <div className="stat-pill">
              <span className="stat-label">Satellites</span>
              <strong>{analysis ? `${analysis.n_clear}/${analysis.n_total}` : "--"}</strong>
            </div>
            <div className="stat-pill">
              <span className="stat-label">Route</span>
              <strong>
                {routeSummary
                  ? `${Math.round(routeSummary.route_coverage_pct)}% clear`
                  : "No plan yet"}
              </strong>
            </div>
          </div>
        </div>
        <div className="reticle">
          <div className="reticle-ring" />
          <div className="reticle-crosshair reticle-h" />
          <div className="reticle-crosshair reticle-v" />
        </div>
      </main>

      <aside className="panel intel-column">
        <section className="panel-block">
          <div className="eyebrow">App Status</div>
          <p>
            {health.loading
              ? "Checking status..."
              : `Status: ${formatOverallStatus(health.data?.status)}`}
          </p>
          <p className="panel-meta">
            {targetPoint
              ? `Selected point: ${targetPoint.lat.toFixed(4)}, ${targetPoint.lon.toFixed(4)}`
              : "Select a target on the map to begin."}
          </p>
          {health.error ? <p className="error-copy">{health.error}</p> : null}
        </section>

        <section className="panel-block">
          <div className="eyebrow">Coverage Summary</div>
          {analysis ? (
            <>
              <div className="intel-list">
                <span>Visible satellites</span>
                <strong>{analysis.visibility?.visible_satellites ?? analysis.n_clear}</strong>
                <span>Blocked satellites</span>
                <strong>{analysis.visibility?.obstructed_satellites ?? analysis.n_total - analysis.n_clear}</strong>
                <span>Blocked sky</span>
                <strong>{Math.round(analysis.obstruction_pct)}%</strong>
              </div>
              <div className="satellite-feed">
                {topSatellites.map((satellite) => (
                  <div className="satellite-item" key={satellite.id}>
                    <div>
                      <strong>{satellite.name || satellite.id}</strong>
                      <span>
                        Azimuth {Math.round(satellite.azimuth)}° • Elevation {Math.round(satellite.elevation)}°
                      </span>
                    </div>
                    <span className={satellite.obstructed ? "status-badge status-badge-bad" : "status-badge"}>
                      {satellite.obstructed ? "Blocked" : "Clear"}
                    </span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <p className="panel-copy">
              No coverage check yet. Click the map or run a check to begin.
            </p>
          )}
        </section>

        <section className="panel-block">
          <div className="eyebrow">Route Summary</div>
          {routeSummary ? (
            <>
              <div className="intel-list">
                <span>Distance</span>
                <strong>{formatDistance(routeSummary.total_distance_m)}</strong>
                <span>Travel time</span>
                <strong>{formatDuration(routeSummary.total_duration_s)}</strong>
                <span>Coverage gaps</span>
                <strong>{routeSummary.num_dead_zones}</strong>
                <span>Longest gap</span>
                <strong>{formatDistance(routeSummary.max_gap_m)}</strong>
              </div>
              <div className="waypoint-feed">
                {routePlan?.waypoints.map((waypoint) => (
                  <div className="waypoint-item" key={waypoint.id}>
                    <strong>{waypoint.name}</strong>
                    <span>
                      {Math.round(waypoint.coverage_pct)}% clear • {formatDuration(waypoint.eta_seconds)} from start
                    </span>
                    {waypoint.best_window ? <span>Best window: {waypoint.best_window}</span> : null}
                  </div>
                ))}
              </div>
            </>
          ) : (
            <p className="panel-copy">
              No route plan yet. Enter a start and end point to compare coverage along a trip.
            </p>
          )}
        </section>

        <section className="panel-block">
          <div className="eyebrow">Coverage Notes</div>
          {dataWarnings.length > 0 ? (
            <ul className="warning-list">
              {dataWarnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : (
            <p className="panel-copy">No coverage notes right now.</p>
          )}
        </section>
      </aside>

      <footer className="panel timeline-strip">
        <span>
          {routePlan?.signal_forecast?.length
            ? `Coverage outlook: ${routePlan.signal_forecast
                .slice(0, 8)
                .map(formatSignalLabel)
                .join(" • ")}`
            : analysis?.timestamp
              ? `Last updated: ${new Date(analysis.timestamp).toLocaleString()}`
              : "Run a coverage check or route plan to see recent activity."}
        </span>
        {hasClassicView ? (
          <button className="text-link-button" onClick={navigateToLegacyConsole}>
            More tools
          </button>
        ) : null}
      </footer>
    </div>
  );
}

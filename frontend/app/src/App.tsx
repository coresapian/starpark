import { useMemo, useState } from "react";

import { BackendClient } from "./lib/api";
import { useBackendHealth } from "./hooks/useBackendHealth";

const client = new BackendClient();

function ledClass(status: string | undefined): string {
  if (status === "healthy") return "led led-green";
  if (status === "degraded") return "led led-amber";
  if (status === "unhealthy") return "led led-red";
  return "led led-muted";
}

export function App(): JSX.Element {
  const [targetLat, setTargetLat] = useState("39.7392");
  const [targetLon, setTargetLon] = useState("-104.9903");
  const [origin, setOrigin] = useState("Denver, CO");
  const [destination, setDestination] = useState("Boulder, CO");
  const [analysisSummary, setAnalysisSummary] = useState<string>("No analysis executed yet.");
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const health = useBackendHealth();
  const isElectronShell = Boolean(window.electronAPI?.isElectron);
  const legacyConsoleUrl = import.meta.env.DEV ? null : "/legacy/";

  const componentMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const component of health.data?.components ?? []) {
      map.set(component.name, component.status);
    }
    return map;
  }, [health.data]);

  async function runAnalyze(): Promise<void> {
    setAnalysisError(null);
    const lat = Number.parseFloat(targetLat);
    const lon = Number.parseFloat(targetLon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
      setAnalysisError("Latitude and longitude must be valid numbers");
      return;
    }
    try {
      const data = await client.analyze({
        lat,
        lon,
        elevation: 0
      });
      setAnalysisSummary(
        `Zone ${data.zone.toUpperCase()} | Clear ${data.n_clear}/${data.n_total} | Obstruction ${Math.round(
          data.obstruction_pct
        )}%`
      );
    } catch (error) {
      setAnalysisError(error instanceof Error ? error.message : "Analyze failed");
    }
  }

  if (legacyConsoleUrl) {
    return (
      <div className="mission-shell mission-shell-hybrid">
        <header className="status-strip panel">
          <div className="status-left">
            <div className={ledClass(health.data?.status)} />
            <span className="status-title">LINKSPOT MISSION CONTROL // HYBRID CUTOVER</span>
          </div>
          <div className="status-right">
            <span className={ledClass(componentMap.get("satellite_engine"))} />
            <span>SAT</span>
            <span className={ledClass(componentMap.get("data_pipeline"))} />
            <span>DATA</span>
            <span className={ledClass(componentMap.get("database"))} />
            <span>DB</span>
            <span className={ledClass(componentMap.get("redis"))} />
            <span>CACHE</span>
          </div>
        </header>

        <main className="panel hybrid-stage">
          <div className="hybrid-banner">
            <div>
              <p className="eyebrow">Runtime Cutover</p>
              <strong>
                React shell is now the {isElectronShell ? "Electron" : "web"} entry renderer.
              </strong>
            </div>
            <span className="hybrid-banner-copy">
              Legacy mission console remains mounted below for full feature coverage during migration.
            </span>
          </div>
          <iframe className="legacy-frame" src={legacyConsoleUrl} title="Legacy LinkSpot mission console" />
        </main>

        <aside className="panel hybrid-intel">
          <section className="panel-block">
            <div className="eyebrow">Backend Posture</div>
            <p>{health.loading ? "Polling backend status..." : `Overall status: ${health.data?.status ?? "unknown"}`}</p>
            {health.error ? <p className="error-copy">{health.error}</p> : null}
          </section>
          <section className="panel-block">
            <div className="eyebrow">Migration Notes</div>
            <ul className="flat-list">
              <li>Typed preload and settings scripts are live in Electron.</li>
              <li>React renderer owns the root shell in packaged desktop and static web delivery.</li>
              <li>Legacy console remains embedded until route/map parity lands.</li>
            </ul>
          </section>
        </aside>
      </div>
    );
  }

  return (
    <div className="mission-shell">
      <header className="status-strip panel">
        <div className="status-left">
          <div className={ledClass(health.data?.status)} />
          <span className="status-title">LINKSPOT MISSION CONTROL // REWRITE TRACK</span>
        </div>
        <div className="status-right">
          <span className={ledClass(componentMap.get("satellite_engine"))} />
          <span>SAT</span>
          <span className={ledClass(componentMap.get("data_pipeline"))} />
          <span>DATA</span>
          <span className={ledClass(componentMap.get("database"))} />
          <span>DB</span>
          <span className={ledClass(componentMap.get("redis"))} />
          <span>CACHE</span>
        </div>
      </header>

      <aside className="panel command-rail">
        <section className="panel-block">
          <div className="eyebrow">Targeting</div>
          <label>
            Latitude
            <input value={targetLat} onChange={(event) => setTargetLat(event.target.value)} />
          </label>
          <label>
            Longitude
            <input value={targetLon} onChange={(event) => setTargetLon(event.target.value)} />
          </label>
          <button className="accent-button" onClick={() => void runAnalyze()}>
            Analyze Position
          </button>
          {analysisError ? <p className="error-copy">{analysisError}</p> : null}
        </section>

        <section className="panel-block">
          <div className="eyebrow">Mission</div>
          <label>
            Origin
            <input value={origin} onChange={(event) => setOrigin(event.target.value)} />
          </label>
          <label>
            Destination
            <input value={destination} onChange={(event) => setDestination(event.target.value)} />
          </label>
          <button className="ghost-button" disabled>
            Route Planning Cutover Pending
          </button>
        </section>
      </aside>

      <main className="panel tactical-stage">
        <div className="stage-grid" />
        <div className="reticle">
          <div className="reticle-ring" />
          <div className="reticle-crosshair reticle-h" />
          <div className="reticle-crosshair reticle-v" />
        </div>
        <div className="stage-copy">
          <p className="eyebrow">Typed Frontend Scaffold</p>
          <h1>Mission-control renderer is now isolated from the legacy global SPA.</h1>
          <p>
            This shell is the typed cutover target for map, timeline, intel, and desktop-integrated
            state. The legacy renderer remains in place until parity checks pass.
          </p>
        </div>
      </main>

      <aside className="panel intel-column">
        <section className="panel-block">
          <div className="eyebrow">Backend Posture</div>
          <p>{health.loading ? "Polling backend status..." : `Overall status: ${health.data?.status ?? "unknown"}`}</p>
          {health.error ? <p className="error-copy">{health.error}</p> : null}
        </section>

        <section className="panel-block">
          <div className="eyebrow">Analysis Feed</div>
          <p>{analysisSummary}</p>
        </section>

        <section className="panel-block">
          <div className="eyebrow">Cutover Notes</div>
          <ul className="flat-list">
            <li>React + TypeScript renderer scaffolded.</li>
            <li>Shared backend client boundary established.</li>
            <li>Legacy SPA stays active until map and route parity complete.</li>
          </ul>
        </section>
      </aside>

      <footer className="panel timeline-strip">
        <span>Timeline and simulation controls will move here during cutover.</span>
      </footer>
    </div>
  );
}

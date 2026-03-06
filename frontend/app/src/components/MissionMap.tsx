import { useEffect, useRef } from "react";
import L from "leaflet";

import type { AnalyzeResponse, RoutePlanResponse } from "../lib/api";

interface TargetPoint {
  lat: number;
  lon: number;
}

interface MissionMapProps {
  target: TargetPoint | null;
  analysis: AnalyzeResponse | null;
  routePlan: RoutePlanResponse | null;
  onSelectTarget: (target: TargetPoint) => void;
}

interface OverlayRefs {
  targetMarker: L.CircleMarker | null;
  routeLayer: L.GeoJSON | null;
  waypointLayer: L.LayerGroup | null;
  deadZoneLayer: L.LayerGroup | null;
}

const DEFAULT_CENTER: L.LatLngExpression = [39.7392, -104.9903];
const TILE_URL = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png";
const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; CARTO';

function escapeHtml(text: string): string {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function zoneColor(zone: string | undefined): string {
  switch (String(zone || "").toLowerCase()) {
    case "excellent":
    case "good":
      return "#5df2cf";
    case "fair":
      return "#f0b057";
    case "poor":
    case "blocked":
      return "#ee6b6b";
    default:
      return "#79b4ff";
  }
}

function signalColor(signal: unknown): string {
  switch (String(signal || "").toLowerCase()) {
    case "clear":
      return "#5df2cf";
    case "marginal":
      return "#f0b057";
    case "dead":
      return "#ee6b6b";
    default:
      return "#7f94ab";
  }
}

function formatZoneLabel(zone: string | undefined): string {
  if (!zone) {
    return "Unknown";
  }
  return zone.charAt(0).toUpperCase() + zone.slice(1).toLowerCase();
}

export function MissionMap({
  target,
  analysis,
  routePlan,
  onSelectTarget
}: MissionMapProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const overlaysRef = useRef<OverlayRefs>({
    targetMarker: null,
    routeLayer: null,
    waypointLayer: null,
    deadZoneLayer: null
  });

  useEffect(() => {
    if (!containerRef.current || mapRef.current) {
      return;
    }

    const map = L.map(containerRef.current, {
      zoomControl: false,
      preferCanvas: true,
      worldCopyJump: true,
      center: DEFAULT_CENTER,
      zoom: 11
    });

    L.tileLayer(TILE_URL, {
      attribution: TILE_ATTRIBUTION,
      maxZoom: 19
    }).addTo(map);

    L.control
      .zoom({
        position: "topright"
      })
      .addTo(map);

    map.on("click", (event: L.LeafletMouseEvent) => {
      onSelectTarget({
        lat: event.latlng.lat,
        lon: event.latlng.lng
      });
    });

    mapRef.current = map;
    window.setTimeout(() => map.invalidateSize(), 0);

    return () => {
      map.remove();
      mapRef.current = null;
      overlaysRef.current = {
        targetMarker: null,
        routeLayer: null,
        waypointLayer: null,
        deadZoneLayer: null
      };
    };
  }, [onSelectTarget]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }

    if (!overlaysRef.current.targetMarker) {
      overlaysRef.current.targetMarker = L.circleMarker(DEFAULT_CENTER, {
        radius: 7,
        color: "#08111d",
        weight: 2,
        fillColor: "#79b4ff",
        fillOpacity: 0.95
      }).addTo(map);
    }

    const marker = overlaysRef.current.targetMarker;
    if (!target) {
      marker.setStyle({ opacity: 0, fillOpacity: 0 });
      return;
    }

    marker
      .setLatLng([target.lat, target.lon])
      .setStyle({
        opacity: 1,
        fillOpacity: 0.95,
        fillColor: zoneColor(analysis?.zone)
      })
      .bindPopup(
        `<strong>Selected point</strong><br>${target.lat.toFixed(5)}, ${target.lon.toFixed(5)}${
          analysis ? `<br>Coverage: ${escapeHtml(formatZoneLabel(analysis.zone))}` : ""
        }`
      );

    if (!routePlan) {
      map.flyTo([target.lat, target.lon], Math.max(map.getZoom(), 13), {
        animate: true,
        duration: 0.7
      });
    }
  }, [analysis, routePlan, target]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }

    overlaysRef.current.routeLayer?.remove();
    overlaysRef.current.waypointLayer?.remove();
    overlaysRef.current.deadZoneLayer?.remove();
    overlaysRef.current.routeLayer = null;
    overlaysRef.current.waypointLayer = null;
    overlaysRef.current.deadZoneLayer = null;

    if (!routePlan) {
      return;
    }

    const routeLayer = L.geoJSON(routePlan.route_geojson as never, {
      style: (feature) => ({
        color: signalColor(feature?.properties?.signal),
        weight: 5,
        opacity: 0.92,
        lineCap: "round",
        lineJoin: "round"
      }),
      onEachFeature: (feature, layer) => {
        const signal = String(feature.properties?.signal || "unknown");
        const visible = Number(feature.properties?.visible_satellites || 0);
        const total = Number(feature.properties?.total_satellites || 0);
        layer.bindTooltip(
          `${formatZoneLabel(signal)} coverage • ${visible}/${total} satellites`
        );
      }
    }).addTo(map);
    overlaysRef.current.routeLayer = routeLayer;

    const waypointLayer = L.layerGroup();
    for (const waypoint of routePlan.waypoints) {
      const marker = L.circleMarker([waypoint.lat, waypoint.lon], {
        radius: 6,
        color: "#ffffff",
        weight: 1.5,
        fillColor: zoneColor(waypoint.zone),
        fillOpacity: 0.95
      });
      marker.bindPopup(
        `<strong>${escapeHtml(waypoint.name || waypoint.id)}</strong><br>` +
          `Coverage: ${Math.round(waypoint.coverage_pct)}%<br>` +
          `Satellites: ${waypoint.visible_satellites}/${waypoint.total_satellites}<br>` +
          `Arrival from start: ${Math.round(waypoint.eta_seconds / 60)} min`
      );
      marker.addTo(waypointLayer);
    }
    waypointLayer.addTo(map);
    overlaysRef.current.waypointLayer = waypointLayer;

    const deadZoneLayer = L.layerGroup();
    for (const deadZone of routePlan.dead_zones) {
      const segment = L.polyline(
        [
          [deadZone.start_lat, deadZone.start_lon],
          [deadZone.end_lat, deadZone.end_lon]
        ],
        {
          color: "#ee6b6b",
          weight: 6,
          opacity: 0.92,
          dashArray: "10 8"
        }
      );
      segment.bindTooltip(`No-coverage stretch • ${(deadZone.length_m / 1000).toFixed(2)} km`);
      segment.addTo(deadZoneLayer);
    }
    deadZoneLayer.addTo(map);
    overlaysRef.current.deadZoneLayer = deadZoneLayer;

    const bounds = routeLayer.getBounds();
    if (bounds.isValid()) {
      map.fitBounds(bounds, {
        padding: [36, 36],
        maxZoom: 14
      });
    }
  }, [routePlan]);

  return <div ref={containerRef} className="mission-map" aria-label="Coverage map" />;
}

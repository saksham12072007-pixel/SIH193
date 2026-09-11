import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CircleMarker,
  GeoJSON,
  MapContainer,
  Popup,
  TileLayer,
  useMap,
} from "react-leaflet";
import type { LatLngBoundsExpression } from "leaflet";
import type { GeoJsonObject } from "geojson";
import "leaflet/dist/leaflet.css";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../../lib/api";
import type { PlotHistory, PlotMarker } from "../../types";

type IrrigationLevel = "safe" | "moderate" | "high";

function irrigationLevel(urgency: string | null | undefined): IrrigationLevel {
  const normalized = urgency?.toUpperCase();
  if (normalized === "SAFE" || normalized === "NO_ACTION") return "safe";
  if (normalized === "URGENT") return "high";
  return "moderate";
}

function irrigationLabel(level: IrrigationLevel): string {
  if (level === "high") return "High irrigation";
  if (level === "moderate") return "Moderate irrigation";
  return "No irrigation";
}

function irrigationColor(level: IrrigationLevel): string {
  if (level === "high") return "#d9574f";
  if (level === "moderate") return "#e5b34f";
  return "#5c9673";
}

// Urgency score per plot: 0 = no irrigation needed, 0.5 = moderate, 1 = high.
function urgencyScore(level: IrrigationLevel): number {
  if (level === "high") return 1;
  if (level === "moderate") return 0.5;
  return 0;
}

// Continuous green -> amber -> red gradient matching irrigationColor's stops,
// so a state's fill blends real proportions instead of snapping to one class.
const URGENCY_GRADIENT: Array<{ stop: number; rgb: [number, number, number] }> = [
  { stop: 0, rgb: [92, 150, 115] },   // safe   (#5c9673)
  { stop: 0.5, rgb: [229, 179, 79] }, // moderate (#e5b34f)
  { stop: 1, rgb: [217, 87, 79] },    // high   (#d9574f)
];

function urgencyToColor(score: number): string {
  const clamped = Math.max(0, Math.min(1, score));
  let lower = URGENCY_GRADIENT[0];
  let upper = URGENCY_GRADIENT[URGENCY_GRADIENT.length - 1];
  for (let index = 0; index < URGENCY_GRADIENT.length - 1; index += 1) {
    if (clamped >= URGENCY_GRADIENT[index].stop && clamped <= URGENCY_GRADIENT[index + 1].stop) {
      lower = URGENCY_GRADIENT[index];
      upper = URGENCY_GRADIENT[index + 1];
      break;
    }
  }
  const range = upper.stop - lower.stop || 1;
  const ratio = (clamped - lower.stop) / range;
  const rgb = lower.rgb.map((channel, index) => Math.round(channel + (upper.rgb[index] - channel) * ratio));
  return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
}

interface RegionAggregate { score: number; count: number }

function computeRegionAggregates(markers: PlotMarker[], key: (marker: PlotMarker) => string | null): Map<string, RegionAggregate> {
  const totals = new Map<string, { sum: number; count: number }>();
  for (const marker of markers) {
    const name = key(marker)?.trim().toLowerCase();
    if (!name) continue;
    const entry = totals.get(name) ?? { sum: 0, count: 0 };
    entry.sum += urgencyScore(irrigationLevel(marker.urgency));
    entry.count += 1;
    totals.set(name, entry);
  }
  const aggregates = new Map<string, RegionAggregate>();
  totals.forEach((value, name) => aggregates.set(name, { score: value.sum / value.count, count: value.count }));
  return aggregates;
}

function FitMapToMarkers({ markers }: { markers: PlotMarker[] }) {
  const map = useMap();

  useEffect(() => {
    if (markers.length === 0) return;
    const bounds: LatLngBoundsExpression = markers.map(marker => [marker.latitude, marker.longitude]);
    map.fitBounds(bounds, { padding: [28, 28], maxZoom: 8 });
  }, [map, markers]);

  return null;
}

function PlotMarkersLayer({ markers, onSelect }: { markers: PlotMarker[]; onSelect: (marker: PlotMarker) => void }) {
  return <>
    {markers.map(marker => {
      const level = irrigationLevel(marker.urgency);
      const color = irrigationColor(level);
      return (
        <CircleMarker
          key={`plot-${marker.plot_id}`}
          center={[marker.latitude, marker.longitude]}
          radius={7}
          pathOptions={{ color: "#ffffff", fillColor: color, fillOpacity: 0.9, opacity: 1, weight: 1.5 }}
          eventHandlers={{ click: () => onSelect(marker) }}
        >
          <Popup>
            <strong>{marker.village ?? marker.district ?? "Field plot"}</strong>
            <br />
            {marker.crop} · {irrigationLabel(level)}
          </Popup>
        </CircleMarker>
      );
    })}
  </>;
}

function StateBoundaryLayer({
  data,
  selectedState,
  aggregates,
  onSelect,
}: {
  data: GeoJsonObject;
  selectedState: string | null;
  aggregates: Map<string, RegionAggregate>;
  onSelect: (state: string) => void;
}) {
  return (
    <GeoJSON
      data={data}
      style={feature => {
        const name = String(feature?.properties?.ST_NM ?? feature?.properties?.NAME_1 ?? "");
        const selected = name.toLowerCase() === selectedState?.toLowerCase();
        const aggregate = aggregates.get(name.toLowerCase());
        return {
          color: selected ? "#173d2c" : "#ffffff",
          weight: selected ? 3 : 0.75,
          // Real choropleth: each state's own advisory mix decides its fill,
          // not whether it's the selected one. No plots yet -> neutral fill.
          fillColor: aggregate ? urgencyToColor(aggregate.score) : "#e4e7e1",
          fillOpacity: aggregate ? 0.75 : 0.35,
        };
      }}
      onEachFeature={(feature, layer) => {
        const name = String(feature.properties?.ST_NM ?? feature.properties?.NAME_1 ?? "");
        if (!name) return;
        const aggregate = aggregates.get(name.toLowerCase());
        layer.bindTooltip(
          aggregate ? `${name} · ${aggregate.count} plot${aggregate.count === 1 ? "" : "s"}` : `${name} · no plots yet`,
          { sticky: true },
        );
        layer.on({ click: () => onSelect(name) });
      }}
    />
  );
}

export function PlotsPage() {
  const [selected, setSelected] = useState<PlotMarker | null>(null);
  const [selectedState, setSelectedState] = useState<string | null>(null);
  const stateBoundaries = useQuery({
    queryKey: ["india-state-boundaries"],
    queryFn: async () => {
      const response = await fetch("https://raw.githubusercontent.com/geohacker/india/master/state/india_state.geojson");
      if (!response.ok) throw new Error("India state boundaries are unavailable.");
      return response.json() as Promise<GeoJsonObject>;
    },
    staleTime: Infinity,
    retry: 1,
  });
  // Fetched unfiltered nationwide so the choropleth reflects every state at
  // once; selectedState only filters which individual markers are drawn.
  const markers = useQuery({
    queryKey: ["plot-markers"],
    queryFn: () => api.get<PlotMarker[]>("/institutional/plots/map"),
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });
  const history = useQuery({
    queryKey: ["plot-history", selected?.plot_id],
    queryFn: () => api.get<PlotHistory>(`/institutional/plots/${selected?.plot_id}/history?days=90`),
    enabled: Boolean(selected),
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });
  const allMarkers = markers.data ?? [];
  const stateAggregates = computeRegionAggregates(allMarkers, marker => marker.state);
  const markerData = selectedState
    ? allMarkers.filter(marker => marker.state?.toLowerCase() === selectedState.toLowerCase())
    : allMarkers;

  return (
    <section className="page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">FIELD INTELLIGENCE</span>
          <h2>Live plot map</h2>
          <p>Real geographic plot locations with current irrigation requirements.</p>
        </div>
        <span className="data-count">{selectedState ? `${selectedState} · ` : ""}{markerData.length} active markers</span>
      </div>
      <div className="plot-layout">
        <div className="map-panel">
          <div className="map-toolbar">
            <span className="eyebrow">REAL-TIME REGIONAL MAP</span>
            <span>
              <i className="map-key safe" /> No irrigation
              <i className="map-key moderate" /> Moderate
              <i className="map-key urgent" /> High
            </span>
          </div>
          <div className="real-map" style={{ height: 520, minHeight: 420 }}>
            {markers.isLoading ? (
              <div className="map-loading"><div className="spinner" /></div>
            ) : stateBoundaries.data || markerData.length ? (
              <MapContainer center={[22.5, 79]} zoom={5} scrollWheelZoom style={{ height: "100%", width: "100%" }}>
                <TileLayer
                  attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                  url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                />
                {stateBoundaries.data && <StateBoundaryLayer data={stateBoundaries.data} selectedState={selectedState} aggregates={stateAggregates} onSelect={state => { setSelectedState(state); setSelected(null); }} />}
                <FitMapToMarkers markers={markerData} />
                {selectedState && <PlotMarkersLayer markers={markerData} onSelect={setSelected} />}
              </MapContainer>
            ) : (
              <div className="empty-state">
                <strong>{selectedState ? `No plots found in ${selectedState}` : "No authorized markers"}</strong>
                <span>{selectedState ? "Choose another state boundary to inspect its plots." : "Markers appear when plots have coordinates in your assigned geography."}</span>
              </div>
            )}
          </div>
          <div className="map-toolbar">
            <span>{selectedState ? `Showing plots in ${selectedState}` : "Click any India state to filter its plots"}</span>
            {selectedState && <button className="secondary-button" onClick={() => { setSelectedState(null); setSelected(null); }}>Show all India</button>}
          </div>
        </div>
        <div className="plot-detail panel">
          {selected ? (
            <>
              <div className="detail-header">
                <div><span className="eyebrow">PLOT DETAIL</span><h3>{selected.village ?? selected.district ?? "Field plot"}</h3></div>
                <button className="icon-button" onClick={() => setSelected(null)} aria-label="Close plot detail">×</button>
              </div>
              <div className="detail-meta">
                <span className={`severity ${irrigationLevel(selected.urgency)}`}>{irrigationLabel(irrigationLevel(selected.urgency))}</span>
                <span className="capitalize">{selected.crop}</span>
                <span>{selected.location_precision.replace("_", " ")}</span>
              </div>
              <div className="detail-stats">
                <div><span>Latitude</span><strong>{selected.latitude.toFixed(4)}</strong></div>
                <div><span>Longitude</span><strong>{selected.longitude.toFixed(4)}</strong></div>
              </div>
              {history.isLoading ? <div className="chart-loading"><div className="spinner" /></div> : history.data?.series.length ? (
                <div className="history-chart">
                  <span className="eyebrow">90-DAY SIGNAL HISTORY</span>
                  <ResponsiveContainer width="100%" height={180}>
                    <LineChart data={history.data.series}>
                      <XAxis dataKey="date" tickFormatter={date => date.slice(5)} tickLine={false} axisLine={false} tick={{ fontSize: 10, fill: "#829087" }} />
                      <YAxis hide domain={["auto", "auto"]} />
                      <Tooltip />
                      <Line type="monotone" dataKey="ndvi" stroke="#4d8d68" dot={false} strokeWidth={2} connectNulls />
                      <Line type="monotone" dataKey="nir" stroke="#d39b4e" dot={false} strokeWidth={2} connectNulls />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : <div className="empty-state compact"><strong>No history available</strong><span>Ingestion data will populate this chart.</span></div>}
            </>
          ) : (
            <div className="empty-state detail-empty"><strong>Select a plot marker</strong><span>Click a marker to inspect its region, coordinates, irrigation level, and history.</span></div>
          )}
        </div>
      </div>
    </section>
  );
}

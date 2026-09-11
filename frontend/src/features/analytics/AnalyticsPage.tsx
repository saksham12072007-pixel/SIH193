import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { api } from "../../lib/api";
import type { Analytics } from "../../types";

export function AnalyticsPage() {
  const analytics = useQuery({ queryKey: ["analytics"], queryFn: () => api.get<Analytics>("/dashboard/analytics?window_days=30") });
  const scatterData = analytics.data?.nir_rainfall_points ?? [];
  const cropData = (analytics.data?.crop_summary ?? []).filter(row => row.avg_nir != null);

  return <section className="page">
    <div className="page-heading"><div><span className="eyebrow">CROSS-FIELD ANALYSIS</span><h2>Analytics</h2><p>Compare crop signals, environmental inputs, and alert severity across the authorized scope.</p></div><button className="secondary-button" onClick={() => analytics.refetch()}>Refresh <span>↻</span></button></div>
    {analytics.data?.suppressed && <div className="notice warning"><strong>Aggregation suppressed.</strong><span>The selected scope does not meet the backend privacy threshold.</span></div>}
    {analytics.isError && <div className="notice warning"><strong>Analytics unavailable.</strong><span>Check your assigned geography and backend connection.</span></div>}
    {analytics.data && !analytics.data.suppressed && <>
      <div className="content-grid">
        <div className="panel chart-panel">
          <div className="panel-heading">
            <div><span className="eyebrow">SIGNAL VS WEATHER / LAST 30 DAYS</span><h3>NIR risk vs rainfall</h3></div>
            <span className="legend"><i className="legend-urgent" /> Per-plot reading</span>
          </div>
          <div className="chart-wrap">
            {scatterData.length === 0 ? <div className="empty-panel"><strong>No observations</strong><span>Points will appear once predictions carry both a rainfall and NIR reading.</span></div> : (
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ left: 4, right: 12, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e4eae5" />
                  <XAxis type="number" dataKey="rainfall_mm" name="Rainfall" unit="mm" axisLine={false} tickLine={false} tick={{ fill: "#7a887f", fontSize: 12 }} />
                  <YAxis type="number" dataKey="nir_percent" name="NIR risk" unit="%" domain={[0, 100]} axisLine={false} tickLine={false} tick={{ fill: "#7a887f", fontSize: 12 }} />
                  <ZAxis range={[24, 24]} />
                  <Tooltip cursor={{ strokeDasharray: "3 3" }} contentStyle={{ border: "1px solid #dce5dd", borderRadius: 8, boxShadow: "0 6px 20px #173d2c14" }} formatter={(value: number, name: string) => [name === "NIR risk" ? `${value}%` : `${value}mm`, name]} />
                  <Scatter data={scatterData} fill="#d56b4e" fillOpacity={0.55} />
                </ScatterChart>
              </ResponsiveContainer>
            )}
          </div>
          <p className="chart-note">Each point is one plot&apos;s rainfall vs. its modeled irrigation risk (NIR) -- more rainfall lowers irrigation risk, matching the water-balance model&apos;s rainfall-saturation logic.</p>
        </div>
        <div className="panel chart-panel">
          <div className="panel-heading"><div><span className="eyebrow">CROP COMPARISON</span><h3>NIR risk by crop</h3></div></div>
          <div className="chart-wrap">
            {cropData.length === 0 ? <div className="empty-panel"><strong>No crop data</strong><span>Crop-level NIR readings will appear once predictions are recorded.</span></div> : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={cropData} layout="vertical" margin={{ left: 12 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e4eae5" horizontal={false} />
                  <XAxis type="number" domain={[0, 100]} axisLine={false} tickLine={false} tick={{ fill: "#7a887f", fontSize: 12 }} />
                  <YAxis type="category" dataKey="name" width={90} axisLine={false} tickLine={false} tick={{ fill: "#173d2c", fontSize: 12 }} />
                  <Tooltip contentStyle={{ border: "1px solid #dce5dd", borderRadius: 8, boxShadow: "0 6px 20px #173d2c14" }} formatter={(value: number) => [`${value}%`, "Avg NIR risk"]} />
                  <Bar dataKey="avg_nir" name="Avg NIR risk" fill="#d56b4e" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      </div>
      <div className="panel analytics-table"><div className="panel-heading"><div><span className="eyebrow">CROP COMPARISON</span><h3>Signal averages</h3></div></div><div className="table-scroll"><table><thead><tr><th>Crop</th><th>Plots</th><th>Avg NIR risk</th><th>Avg NDVI</th><th>Rainfall / 7d</th></tr></thead><tbody>{analytics.data.crop_summary.map(row => <tr key={row.name}><td className="capitalize"><strong>{row.name}</strong></td><td>{row.count}</td><td>{row.avg_nir ?? "--"}%</td><td>{row.avg_ndvi ?? "--"}</td><td>{row.avg_rainfall_7d ?? "--"} mm</td></tr>)}</tbody></table></div></div>
      <div className="panel analytics-table"><div className="panel-heading"><div><span className="eyebrow">DISTRICT SEVERITY</span><h3>Alert distribution</h3></div></div><div className="district-list">{analytics.data.alerts_by_district.map(row => <div className="district-row" key={row.name}><strong>{row.name}</strong><span className="severity safe">{row.safe} safe</span><span className="severity moderate">{row.moderate} moderate</span><span className="severity high">{row.high} high</span><span className="severity urgent">{row.urgent} urgent</span></div>)}</div></div>
    </>}
  </section>;
}

import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import type { DataQuality } from "../../types";

const checks: Array<[keyof DataQuality, string]> = [
  ["farmerRecords", "Complete farmer records"], ["farmCoordinates", "Plot coordinates"],
  ["nirData", "NIR coverage"], ["ndviData", "NDVI coverage"], ["weatherData", "Weather coverage"],
];

export function DataQualityPage() {
  const { user } = useAuth();
  const quality = useQuery({ queryKey: ["data-quality"], queryFn: () => api.get<DataQuality>("/institutional/data-quality?window_days=14"), enabled: user?.role === "admin" });
  if (user?.role !== "admin") return <section className="page"><div className="notice warning"><strong>Administrator access required.</strong><span>Data quality metrics are restricted to institutional administrators.</span></div></section>;
  return <section className="page"><div className="page-heading"><div><span className="eyebrow">ADMIN QUALITY CONTROL</span><h2>Data quality</h2><p>Completeness and freshness checks for the current operational dataset.</p></div><button className="secondary-button" onClick={() => quality.refetch()}>Refresh <span>↻</span></button></div>
    {quality.isError && <div className="notice warning"><strong>Quality metrics unavailable.</strong><span>The endpoint requires an administrator session.</span></div>}
    {quality.data && <><div className="quality-grid">{checks.map(([key, label]) => <div className="quality-card" key={key}><div className="quality-card-head"><span>{label}</span><strong>{quality.data[key]}%</strong></div><div className="quality-bar"><i style={{ width: `${quality.data[key]}%` }} /></div><small>Last {quality.data.windowDays} days</small></div>)}</div><div className="metric-grid quality-summary"><div className="metric-card"><span className="metric-label">Farmers</span><strong>{quality.data.totalFarmers}</strong><span className="metric-detail">Total records</span></div><div className="metric-card"><span className="metric-label">Plots</span><strong>{quality.data.totalPlots}</strong><span className="metric-detail">Registered plots</span></div><div className="metric-card accent-amber"><span className="metric-label">Missing records</span><strong>{quality.data.missingRecords}</strong><span className="metric-detail">Need enrichment</span></div><div className="metric-card accent-red"><span className="metric-label">Outdated data</span><strong>{quality.data.outdatedData}</strong><span className="metric-detail">Unavailable or stale</span></div></div><div className="panel quality-issues"><div className="panel-heading"><div><span className="eyebrow">REVIEW QUEUE</span><h3>Data issues</h3></div></div><div className="issue-list"><Issue label="Invalid/village fallback coordinates" value={quality.data.invalidCoordinates} /><Issue label="Potential duplicate farmers" value={quality.data.duplicateFarmers} /><Issue label="Missing farmer records" value={quality.data.missingRecords} /></div></div></>}
    {!quality.isLoading && !quality.data && !quality.isError && <div className="empty-panel"><h2>No quality data</h2><p>Metrics will appear when the backend returns an authorized quality report.</p></div>}
  </section>;
}
function Issue({ label, value }: { label: string; value: number }) { return <div className="issue-row"><span>{label}</span><strong>{value}</strong></div>; }

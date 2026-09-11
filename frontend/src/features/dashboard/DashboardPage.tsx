import { useQuery } from "@tanstack/react-query";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../../lib/api";
import type { DashboardAggregates, DashboardTrends, OperationsStatus } from "../../types";

export function DashboardPage() {
  const liveQueryOptions = { refetchInterval: 30_000, refetchOnWindowFocus: true };
  const aggregates = useQuery({ queryKey: ["dashboard", "aggregates"], queryFn: () => api.get<DashboardAggregates>("/dashboard/aggregates"), ...liveQueryOptions });
  const trends = useQuery({ queryKey: ["dashboard", "trends"], queryFn: () => api.get<DashboardTrends>("/dashboard/trends?window_days=14"), ...liveQueryOptions });
  const operations = useQuery({ queryKey: ["operations", "status"], queryFn: () => api.get<OperationsStatus>("/institutional/operations/status"), ...liveQueryOptions });
  const data = aggregates.data;
  const summary = data?.summary;
  // Plotted as each day's share of plots (%), not raw counts: the total
  // number of advised plots grows over time (new farmers/plots onboard,
  // datasets get imported), so an absolute-count chart would always show a
  // "spike" on any day plot count jumps, whether or not the actual crop
  // health mix changed. Percent-of-day stays meaningful either way.
  const trendData = (trends.data?.series ?? []).map(point => {
    const total = point.no_action + point.monitor + point.irrigate_soon + point.irrigate_now;
    const pct = (value: number) => (total > 0 ? Math.round((value / total) * 1000) / 10 : 0);
    return {
      day: new Date(`${point.date}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
      safe: pct(point.no_action),
      moderate: pct(point.monitor + point.irrigate_soon),
      urgent: pct(point.irrigate_now),
      plots: total,
    };
  });
  return <section className="page">
    <div className="page-heading"><div><span className="eyebrow">OVERVIEW / LAST 14 DAYS</span><h2>Field pulse</h2><p>One view of crop stress, response, and operational health.</p></div><button className="secondary-button" onClick={() => { void aggregates.refetch(); void trends.refetch(); void operations.refetch(); }}>Refresh data <span>↻</span></button></div>
    {(aggregates.isError || trends.isError || operations.isError) && <div className="notice warning"><strong>Some live data is unavailable.</strong><span>Check the backend connection and retry. The cards below may be incomplete.</span></div>}
    <div className="metric-grid">
      <Metric label="Active plots" value={data?.total_plots ?? operations.data?.plots.active ?? "--"} detail="Authorized in current scope" accent="green" />
      <Metric label="Alert rate" value={data ? `${data.alert_rate}%` : "--"} detail="Plots needing attention" accent="amber" />
      <Metric label="Urgent action" value={summary?.irrigate_now ?? "--"} detail="Irrigate now" accent="red" />
      <Metric label="Delivery rate" value={operations.data?.delivery.delivered_rate_percent != null ? `${operations.data.delivery.delivered_rate_percent}%` : "--"} detail="SMS delivered" accent="blue" />
    </div>
    <div className="content-grid"><div className="panel chart-panel"><div className="panel-heading"><div><span className="eyebrow">ADVISORY MIX / LAST 14 DAYS</span><h3>Signal movement</h3></div><span className="legend"><i className="legend-safe" /> Safe <i style={{ background: "#e5b34f" }} /> Moderate <i className="legend-urgent" /> Urgent {trends.isFetching && trends.data ? <small>Updating…</small> : null}</span></div><div className="chart-wrap">{trends.data?.suppressed ? <div className="empty-panel"><strong>Trend suppressed</strong><span>The selected scope does not meet the backend privacy threshold.</span></div> : trendData.length === 0 ? <div className="empty-panel"><strong>No trend observations</strong><span>Trend points will appear when advisories are recorded.</span></div> : <ResponsiveContainer width="100%" height="100%"><AreaChart data={trendData}><defs><linearGradient id="safeFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#5c9673" stopOpacity=".3" /><stop offset="100%" stopColor="#5c9673" stopOpacity="0" /></linearGradient></defs><XAxis dataKey="day" axisLine={false} tickLine={false} tick={{ fill: "#7a887f", fontSize: 12 }} /><YAxis hide domain={[0, 100]} allowDecimals={false} /><Tooltip contentStyle={{ border: "1px solid #dce5dd", borderRadius: 8, boxShadow: "0 6px 20px #173d2c14" }} formatter={(value: number, name: string) => [`${value}%`, name]} labelFormatter={(label, payload) => payload?.[0] ? `${label} · ${payload[0].payload.plots} plots` : label} /><Area type="monotone" dataKey="safe" name="Safe" stroke="#5c9673" fill="url(#safeFill)" strokeWidth={2} /><Area type="monotone" dataKey="moderate" name="Moderate" stroke="#e5b34f" fill="none" strokeWidth={2} /><Area type="monotone" dataKey="urgent" name="Urgent" stroke="#d56b4e" fill="none" strokeWidth={2} /></AreaChart></ResponsiveContainer>}</div></div><div className="panel"><div className="panel-heading"><div><span className="eyebrow">CURRENT DISTRIBUTION</span><h3>Irrigation requirement</h3></div></div><div className="status-list"><StatusRow label="No irrigation" value={summary ? summary.no_action : "--"} tone="safe" /><StatusRow label="Moderate irrigation" value={summary ? summary.monitor + summary.irrigate_soon : "--"} tone="moderate" /><StatusRow label="High irrigation" value={summary ? summary.irrigate_now : "--"} tone="urgent" /></div></div></div>
    <div className="section-heading"><div><span className="eyebrow">WORKFLOW HEALTH</span><h3>Operations at a glance</h3></div></div><div className="operation-grid"><Operation label="Observations ingested" value={operations.data?.plots.successful_observations ?? "--"} detail="Successful records" /><Operation label="Predictions processed" value={operations.data?.processing.predictions_total ?? "--"} detail="All time in scope" /><Operation label="Active alerts" value={operations.data?.alerts.total ?? "--"} detail="Across current scope" /></div>
    {data?.suppressed && <div className="notice"><strong>Privacy threshold applied.</strong><span>Aggregates are suppressed because the selected scope contains fewer than the required number of plots.</span></div>}
  </section>;
}

function Metric({ label, value, detail, accent }: { label: string; value: string | number; detail: string; accent: string }) { return <div className={`metric-card accent-${accent}`}><span className="metric-label">{label}</span><strong>{value}</strong><span className="metric-detail">{detail}</span></div>; }
function StatusRow({ label, value, tone }: { label: string; value: string | number; tone: string }) { return <div className="status-row"><span><i className={`status-dot ${tone}`} />{label}</span><strong>{value}</strong></div>; }
function Operation({ label, value, detail }: { label: string; value: string | number; detail: string }) { return <div className="operation-card"><span className="eyebrow">{label}</span><strong>{value}</strong><span>{detail}</span></div>; }

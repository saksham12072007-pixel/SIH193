import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { OperationsStatus } from "../../types";

export function OperationsPage() {
  const operations = useQuery({ queryKey: ["operations", "status"], queryFn: () => api.get<OperationsStatus>("/institutional/operations/status") });
  if (operations.isLoading) return <section className="page"><div className="table-loading"><div className="spinner" /></div></section>;
  if (operations.isError || !operations.data) return <section className="page"><div className="notice warning"><strong>Operations status unavailable.</strong><span>Retry after the backend readiness check succeeds.</span><button className="secondary-button" onClick={() => operations.refetch()}>Retry ↻</button></div></section>;
  const status = operations.data;
  return <section className="page"><div className="page-heading"><div><span className="eyebrow">SYSTEM OPERATIONS</span><h2>Operations</h2><p>Monitor ingestion, model processing, alerts, and message delivery across the authorized scope.</p></div><button className="secondary-button" onClick={() => operations.refetch()}>Refresh <span>↻</span></button></div><div className="metric-grid"><Metric label="Active plots" value={status.plots.active} detail={`${status.plots.ingested_last_24h} ingested in 24h`} /><Metric label="Predictions" value={status.processing.predictions_total} detail={`${status.processing.predictions_last_24h} in 24h`} /><Metric label="Advisories" value={status.processing.advisories_total} detail={`${status.processing.advisories_last_24h} in 24h`} /><Metric label="Alerts" value={status.alerts.total} detail="Across current scope" /></div><div className="content-grid"><div className="panel"><div className="panel-heading"><div><span className="eyebrow">DATA PIPELINE</span><h3>Ingestion health</h3></div></div><div className="status-list"><Row label="Successful observations" value={status.plots.successful_observations} /><Row label="Ingested in last 24 hours" value={status.plots.ingested_last_24h} />{Object.entries(status.plots.data_status).map(([label, value]) => <Row key={label} label={label.replace(/_/g, " ")} value={value} />)}</div></div><div className="panel"><div className="panel-heading"><div><span className="eyebrow">MESSAGING</span><h3>Delivery status</h3></div></div><div className="status-list"><Row label="Total messages" value={status.delivery.total_messages} /><Row label="Delivered rate" value={status.delivery.delivered_rate_percent === null ? "--" : `${status.delivery.delivered_rate_percent}%`} />{Object.entries(status.delivery.by_status).map(([label, value]) => <Row key={label} label={label.replace(/_/g, " ")} value={value} />)}</div></div></div><p className="form-note">Generated {new Date(status.generated_at).toLocaleString()}</p></section>;
}

function Metric({ label, value, detail }: { label: string; value: number; detail: string }) {
  return <div className="metric-card"><span className="metric-label">{label}</span><strong>{value}</strong><span className="metric-detail">{detail}</span></div>;
}

function Row({ label, value }: { label: string; value: number | string }) {
  return <div className="status-row"><span className="capitalize">{label}</span><strong>{value}</strong></div>;
}

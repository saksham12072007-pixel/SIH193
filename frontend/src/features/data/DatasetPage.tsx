import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { DatasetUploadResult } from "../../types";

export function DatasetPage() {
  const [file, setFile] = useState<File | null>(null);
  const queryClient = useQueryClient();
  const upload = useMutation({
    mutationFn: async () => { if (!file) throw new Error("Select a file first"); const form = new FormData(); form.append("file", file); return api.post<DatasetUploadResult>("/api/datasets/datasets/upload", form); },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["operations"] });
      void queryClient.invalidateQueries({ queryKey: ["analytics"] });
    },
  });
  return <section className="page"><div className="page-heading"><div><span className="eyebrow">DATA OPERATIONS</span><h2>Dataset import</h2><p>Import farm, plot, and telemetry records into the authorized workspace.</p></div></div><div className="upload-panel"><div className="upload-icon">↑</div><h3>Upload CSV or Excel</h3><p>Required columns: <code>plot_id</code>, <code>lat</code>, <code>lon</code>, <code>crop</code>, <code>soil_type</code>, <code>sowing_date</code>.</p><input id="dataset-file" type="file" accept=".csv,.xlsx,.xls" onChange={e => setFile(e.target.files?.[0] ?? null)} /><label htmlFor="dataset-file" className="file-picker">{file ? file.name : "Choose a CSV or Excel file"}</label><button className="primary-button upload-button" disabled={!file || upload.isPending} onClick={() => upload.mutate()}>{upload.isPending ? "Importing..." : "Import dataset"}</button></div>{upload.isError && <div className="notice warning"><strong>Import failed.</strong><span>{upload.error instanceof Error ? upload.error.message : "The dataset could not be processed."}</span></div>}{upload.data && <div className="metric-grid import-results"><div className="metric-card"><span className="metric-label">Inserted</span><strong>{upload.data.rows_inserted}</strong></div><div className="metric-card"><span className="metric-label">Updated</span><strong>{upload.data.rows_updated}</strong></div><div className="metric-card accent-red"><span className="metric-label">Row errors</span><strong>{upload.data.total_errors}</strong></div><div className="metric-card"><span className="metric-label">Predictions generated</span><strong>{upload.data.predictions_generated}</strong></div><div className="metric-card"><span className="metric-label">Advisories generated</span><strong>{upload.data.advisories_generated}</strong></div></div>}
    {upload.data && upload.data.predictions_generated === 0 && (upload.data.rows_inserted > 0 || upload.data.rows_updated > 0) && <div className="notice warning"><strong>No predictions were generated for this import.</strong><span>The dashboard only updates for rows that included at least one of <code>ndvi</code>, <code>rainfall</code>, or <code>temperature</code> — add one of those columns to your file, or the imported plots have no data for the model to score yet.</span></div>}
    {upload.data && upload.data.predictions_generated > 0 && <div className="notice"><strong>Dashboard updated.</strong><span>{upload.data.predictions_generated} prediction(s) and {upload.data.advisories_generated} advisory record(s) were generated for the imported plots.</span></div>}{upload.data?.errors.length ? <div className="table-panel"><div className="table-toolbar"><span className="eyebrow">INVALID ROWS</span></div><table><thead><tr><th>Row</th><th>Reason</th></tr></thead><tbody>{upload.data.errors.map(item => <tr key={item.row}><td>{item.row}</td><td>{item.error}</td></tr>)}</tbody></table></div> : null}</section>;
}

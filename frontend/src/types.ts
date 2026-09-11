export type InstitutionalRole = "admin" | "district_officer" | "field_officer" | "analyst";

export interface InstitutionalUser {
  user_id: string;
  email: string;
  role: InstitutionalRole;
  assigned_geography: { states?: string[]; districts?: string[] };
}

export interface Farmer {
  farmer_id: string;
  phone_number: string;
  name: string | null;
  preferred_language: string;
  state: string | null;
  district: string | null;
  registration_channel: string;
  status: string;
  consent_given_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface FarmerSession {
  farmer_id: string;
  phone_number: string;
  session_token: string;
  token_type: string;
}

export interface FarmerPlot {
  plot_id: string;
  farmer_id: string;
  plot_nickname: string | null;
  location_precision: string;
  village_name: string | null;
  crop_type: string;
  plot_size_declared: number | null;
  sowing_date: string | null;
  soil_texture: string | null;
  irrigation_type: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface FarmerAdvisory {
  advisory_id: string;
  plot_id: string;
  prediction_id: string;
  advisory_class: string;
  language_used: string | null;
  sms_sent: boolean;
  ivr_triggered: boolean;
  created_at: string;
}

export interface ApiErrorBody {
  error?: { code?: string; message?: string };
  detail?: string;
  request_id?: string;
}

export interface DashboardAggregates {
  scope: string;
  window_days: number;
  suppressed: boolean;
  total_plots: number;
  alert_rate: number;
  nri_percent: number | null;
  nri_plot_count: number;
  summary: {
    no_action: number;
    monitor: number;
    irrigate_soon: number;
    irrigate_now: number;
  };
  districts?: Array<{
    name: string;
    totalFarms: number;
    urgent: number;
    moderate: number;
    safe: number;
    avgNir: number | null;
    avgNdvi: number | null;
    avgRainfall: number | null;
    primaryCrop: string;
  }>;
}

export interface DashboardTrends {
  scope: string;
  window_days: number;
  suppressed: boolean;
  series: Array<{
    date: string;
    no_action: number;
    monitor: number;
    irrigate_soon: number;
    irrigate_now: number;
  }>;
}

export interface OperationsStatus {
  generated_at: string;
  plots: { active: number; ingested_last_24h: number; successful_observations: number; data_status: Record<string, number> };
  processing: { predictions_total: number; predictions_last_24h: number; advisories_total: number; advisories_last_24h: number };
  alerts: { total: number; by_status: Record<string, number> };
  delivery: { total_messages: number; delivered_rate_percent: number | null; by_status: Record<string, number> };
}

export interface AlertRecord {
  alert_id: string;
  plot_id: string;
  farmer_id: string;
  farmer_name: string;
  district: string | null;
  crop: string;
  severity: "SAFE" | "MODERATE" | "HIGH" | "URGENT";
  title: string;
  description: string;
  status: string;
  assigned_user_id: string | null;
  resolution_notes: string | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
}

export interface PlotMarker {
  plot_id: string;
  farmer_id: string;
  crop: string;
  state: string | null;
  district: string | null;
  village: string | null;
  latitude: number;
  longitude: number;
  location_precision: string;
  observed_at: string | null;
  ndvi: number | null;
  nir: number | null;
  status: string;
  urgency: string | null;
}

export interface PlotHistory {
  plot_id: string;
  crop: string;
  location_precision: string;
  series: Array<{ date: string; ndvi: number | null; nir: number | null; rainfall_7d: number | null }>;
}

export interface FieldInspection {
  inspection_id: string;
  plot_id: string;
  farmer_name: string;
  district: string | null;
  crop: string;
  officer_name: string;
  issue_type: string;
  observed_condition: string | null;
  severity: string;
  farmer_comments: string | null;
  officer_comments: string | null;
  gps_lat: number | null;
  gps_lng: number | null;
  gps_accuracy_m: number | null;
  photos: string[];
  recommended_action: string | null;
  status: string;
  inspection_date: string;
}

export interface AlertRule {
  rule_id: string;
  name: string;
  metric: string;
  operator: string;
  value: number;
  severity: string;
  district: string | null;
  crop: string | null;
  enabled: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface Prediction {
  prediction_id: string; plot_id: string; predicted_class: string; confidence: number | null;
  soil_moisture_pct: number | null; nir_percent: number | null; advice: string | null;
  urgency: string | null; reason: string | null; fallback_used: boolean; model_version: string | null;
  reason_code: string | null; created_at: string;
}
export interface IngestionLatest { plot_id: string; ndvi: Array<{ date: string; value: string; cloud_coverage?: number }>; sar: Array<{ date: string; value: string }>; weather: Array<{ date: string; value: string }>; }
export interface ModelHealth { agro_zone: string | null; fpr_threshold: number; model_versions: Array<{ model_version: string; agro_zone: string | null; trained_at: string | null; stage1_rmse: number | null; stage1_r2: number | null; stage2_recall: number | null; stage2_fpr: number | null; passed_fpr_threshold: boolean }>; fpr_alerts: Array<{ model_version: string; fpr: number; threshold: number; alert: string }>; has_alerts: boolean; }
export interface DatasetUploadResult { filename: string; rows_inserted: number; rows_updated: number; total_errors: number; errors: Array<{ row: number; error: string }>; predictions_generated: number; advisories_generated: number; }
export interface PredictionExplanation {
  prediction_id: string; plot_id: string; advisory_class: string; confidence_score: number | null;
  reason_code: string | null; stage1_soil_moisture_pct: number | null; stage1_cwsi: number | null;
  feature_impacts: Record<string, { value: string | number; impact: number; direction: string; note: string }>;
  base_explanation: string; model_version: string | null;
}
export interface DataQuality {
  farmerRecords: number; farmCoordinates: number; nirData: number; ndviData: number;
  weatherData: number; missingRecords: number; invalidCoordinates: number;
  duplicateFarmers: number; outdatedData: number; totalFarmers: number;
  totalPlots: number; windowDays: number; generatedAt: string;
}
export interface Analytics {
  scope: string; window_days: number; suppressed: boolean;
  observations: Array<{ plot_id: string; district: string | null; crop: string; nir_percent: number; ndvi: number | null; rainfall_7d: number | null; urgency: string }>;
  crop_summary: Array<{ name: string; count: number; avg_nir: number | null; avg_ndvi: number | null; avg_rainfall_7d: number | null }>;
  alerts_by_district: Array<{ name: string; safe: number; moderate: number; high: number; urgent: number }>;
  nir_rainfall_points: Array<{ rainfall_mm: number; nir_percent: number }>;
}
export interface InstitutionalUserRecord {
  user_id: string; email: string; role: InstitutionalRole; assigned_geography: { states?: string[]; districts?: string[] };
  created_at: string; last_login_at: string | null;
}

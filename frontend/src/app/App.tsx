import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { AppShell } from "../layouts/AppShell";
import { useFarmerAuth } from "../lib/farmerAuth";

const LoginPage = lazy(() => import("../features/auth/LoginPage").then(module => ({ default: module.LoginPage })));
const SignupPage = lazy(() => import("../features/auth/SignupPage").then(module => ({ default: module.SignupPage })));
const DashboardPage = lazy(() => import("../features/dashboard/DashboardPage").then(module => ({ default: module.DashboardPage })));
const AlertsPage = lazy(() => import("../features/alerts/AlertsPage").then(module => ({ default: module.AlertsPage })));
const AlertRulesPage = lazy(() => import("../features/alerts/AlertRulesPage").then(module => ({ default: module.AlertRulesPage })));
const PlotsPage = lazy(() => import("../features/plots/PlotsPage").then(module => ({ default: module.PlotsPage })));
const InspectionsPage = lazy(() => import("../features/inspections/InspectionsPage").then(module => ({ default: module.InspectionsPage })));
const IntelligencePage = lazy(() => import("../features/intelligence/IntelligencePage").then(module => ({ default: module.IntelligencePage })));
const DatasetPage = lazy(() => import("../features/data/DatasetPage").then(module => ({ default: module.DatasetPage })));
const ModelMonitoringPage = lazy(() => import("../features/model/ModelMonitoringPage").then(module => ({ default: module.ModelMonitoringPage })));
const DataQualityPage = lazy(() => import("../features/data/DataQualityPage").then(module => ({ default: module.DataQualityPage })));
const AnalyticsPage = lazy(() => import("../features/analytics/AnalyticsPage").then(module => ({ default: module.AnalyticsPage })));
const UserManagementPage = lazy(() => import("../features/admin/UserManagementPage").then(module => ({ default: module.UserManagementPage })));
const OperationsPage = lazy(() => import("../features/operations/OperationsPage").then(module => ({ default: module.OperationsPage })));
const FarmerLoginPage = lazy(() => import("../features/farmer/FarmerLoginPage").then(module => ({ default: module.FarmerLoginPage })));
const FarmerRegisterPage = lazy(() => import("../features/farmer/FarmerRegisterPage").then(module => ({ default: module.FarmerRegisterPage })));
const FarmerDashboardPage = lazy(() => import("../features/farmer/FarmerDashboardPage").then(module => ({ default: module.FarmerDashboardPage })));
const MessagingPage = lazy(() => import("../features/operations/MessagingPage").then(module => ({ default: module.MessagingPage })));

function RouteLoading() {
  return <div className="screen-center"><div className="spinner" /></div>;
}

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { token, isLoading } = useAuth();
  if (isLoading) return <RouteLoading />;
  return token ? children : <Navigate to="/login" replace />;
}

function FarmerRoute({ children }: { children: ReactNode }) {
  const { session } = useFarmerAuth();
  return session ? children : <Navigate to="/farmer/login" replace />;
}

export function App() {
  return <Suspense fallback={<RouteLoading />}>
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/farmer/login" element={<FarmerLoginPage />} />
      <Route path="/farmer/register" element={<FarmerRegisterPage />} />
      <Route path="/farmer" element={<FarmerRoute><FarmerDashboardPage /></FarmerRoute>} />
      <Route path="/" element={<ProtectedRoute><AppShell /></ProtectedRoute>}>
        <Route index element={<DashboardPage />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="alerts" element={<AlertsPage />} />
        <Route path="alert-rules" element={<AlertRulesPage />} />
        <Route path="map" element={<PlotsPage />} />
        <Route path="plots" element={<Navigate to="/map" replace />} />
        <Route path="inspections" element={<InspectionsPage />} />
        <Route path="advisories" element={<IntelligencePage />} />
        <Route path="ingestion" element={<Navigate to="/advisories" replace />} />
        <Route path="dataset-import" element={<DatasetPage />} />
        <Route path="model-monitoring" element={<ModelMonitoringPage />} />
        <Route path="data-quality" element={<DataQualityPage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="operations" element={<OperationsPage />} />
        <Route path="messaging" element={<MessagingPage />} />
        <Route path="users" element={<UserManagementPage />} />
        <Route path="*" element={<div className="empty-panel"><h2>Module coming next</h2><p>This route is reserved for the next implementation phase.</p></div>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  </Suspense>;
}

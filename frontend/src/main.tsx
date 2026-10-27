import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { AppProvider, useApp } from "./context";
import Admin from "./pages/Admin";
import Connectors from "./pages/Connectors";
import Dashboard from "./pages/Dashboard";
import Evidence from "./pages/Evidence";
import ImportWizard from "./pages/ImportWizard";
import Inventory from "./pages/Inventory";
import Login from "./pages/Login";
import Outcomes from "./pages/Outcomes";
import Settings from "./pages/Settings";
import Validation from "./pages/Validation";
import ValuationDetail from "./pages/ValuationDetail";
import PiDashboard from "./pages/pi/PiDashboard";
import PiExceptions from "./pages/pi/PiExceptions";
import PiHistory from "./pages/pi/PiHistory";
import PiImport from "./pages/pi/PiImport";
import PiNewValuation from "./pages/pi/PiNewValuation";
import PiQuotations from "./pages/pi/PiQuotations";
import PiReports from "./pages/pi/PiReports";
import PiResearch from "./pages/pi/PiResearch";
import PiReview from "./pages/pi/PiReview";
import PiRules from "./pages/pi/PiRules";
import PiSources from "./pages/pi/PiSources";
import "./styles.css";

function Gate() {
  const { user, loading } = useApp();
  if (loading) {
    return (
      <div className="splash" aria-busy="true">
        <img src="/brand/casterly-mark.png" alt="Casterly" />
      </div>
    );
  }
  if (!user) return <Login />;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="import" element={<ImportWizard />} />
        <Route path="import/:batchId" element={<ImportWizard />} />
        <Route path="inventory" element={<Inventory />} />
        <Route path="valuations/:runId" element={<ValuationDetail />} />
        <Route path="evidence" element={<Evidence />} />
        <Route path="outcomes" element={<Outcomes />} />
        <Route path="settings" element={<Settings />} />
        <Route path="validation" element={<Validation />} />
        <Route path="connectors" element={<Connectors />} />
        <Route path="admin" element={<Admin />} />
        <Route path="pi" element={<PiDashboard />} />
        <Route path="pi/new" element={<PiNewValuation />} />
        <Route path="pi/import" element={<PiImport />} />
        <Route path="pi/research" element={<PiResearch />} />
        <Route path="pi/review" element={<PiReview />} />
        <Route path="pi/quotations" element={<PiQuotations />} />
        <Route path="pi/history" element={<PiHistory />} />
        <Route path="pi/sources" element={<PiSources />} />
        <Route path="pi/rules" element={<PiRules />} />
        <Route path="pi/exceptions" element={<PiExceptions />} />
        <Route path="pi/reports" element={<PiReports />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppProvider>
      <BrowserRouter>
        <Gate />
      </BrowserRouter>
    </AppProvider>
  </StrictMode>,
);

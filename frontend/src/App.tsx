import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy } from "react";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes as RouterRoutes,
} from "react-router-dom";
import { Layout } from "./components/Layout";
const Districts = lazy(() => import("./pages/Districts"));
const WarehousesExplorer = lazy(() => import("./pages/Intelligence").then(m => ({ default: m.WarehousesExplorer })));
const MarketsExplorer = lazy(() => import("./pages/MarketIntelligence").then(m => ({ default: m.MarketsExplorer })));
const Strategies = lazy(() => import("./pages/Strategies").then(m => ({ default: m.Strategies })));
const AlternativePlan = lazy(() => import("./pages/AlternativePlan"));
const HistoricalMarkets = lazy(() => import("./pages/Markets"));
const Overview = lazy(() => import("./pages/Overview"));
const Outlook = lazy(() => import("./pages/Outlook"));
const Today = lazy(() => import("./pages/Today"));
const Routes = lazy(() => import("./pages/Routes").then(m => ({ default: m.Routes })));
const WarehouseSources = lazy(() => import("./pages/Routes").then(m => ({ default: m.Warehouses })));

export function AppRoutes() {
  return (
    <RouterRoutes>
      <Route element={<Layout />}>
        <Route index element={<Strategies />} />
        <Route path="strategies/plan/:planId" element={<AlternativePlan />} />
        <Route path="markets" element={<MarketsExplorer />} />
        <Route path="today" element={<Today />} />
        <Route path="districts" element={<Districts />} />
        <Route path="outlook" element={<Outlook />} />
        <Route path="routes" element={<Routes />} />
        <Route path="warehouses" element={<WarehousesExplorer />} />
        <Route path="history" element={<Overview />} />
        <Route path="history/markets" element={<HistoricalMarkets />} />
        <Route path="history/warehouses" element={<WarehouseSources />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </RouterRoutes>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={new QueryClient()}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}

import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Production from "./pages/Production";
import Evaluation from "./pages/Evaluation";
import EvaluationInsight from "./pages/EvaluationInsight";
import EntryAnalysis from "./pages/EntryAnalysis";
import Portfolio from "./pages/Portfolio";
import TradeHistory from "./pages/TradeHistory";
import Signals from "./pages/Signals";
import StockDetail from "./pages/StockDetail";
import Strategies from "./pages/Strategies";
import Stocks from "./pages/Stocks";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/production" element={<Production />} />
        <Route path="/evaluation" element={<Evaluation />} />
        <Route path="/evaluation-insight" element={<EvaluationInsight />} />
        <Route path="/entry-analysis" element={<EntryAnalysis />} />
        <Route path="/portfolio" element={<Portfolio />} />
        <Route path="/trade-history" element={<TradeHistory />} />
        <Route path="/signals" element={<Signals />} />
        <Route path="/stocks" element={<Stocks />} />
        <Route path="/stock/:ticker" element={<StockDetail />} />
        <Route path="/strategies" element={<Strategies />} />
      </Route>
    </Routes>
  );
}

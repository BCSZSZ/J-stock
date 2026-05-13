import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import {
  compareSignalsForDisplay,
  getDisplayAction,
  getExecutableBuy,
  getExecutableSell,
  getExecutionLabel,
  getMomentumRank,
  getMomentumValue,
  getSellIntent,
  getSellOrderLabel,
  getSellPeriodLabel,
  getSellPlanLabel,
  getSellTriggerLabel,
} from "../signalSemantics";
import { useTickerNames } from "../hooks/useTickerNames";

export default function Signals() {
  const dates = useQuery({ queryKey: ["signal-dates"], queryFn: api.signalDates });
  const [searchParams] = useSearchParams();
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [viewReport, setViewReport] = useState(searchParams.get("view") === "report");
  const names = useTickerNames();

  const signals = useQuery({
    queryKey: ["signals", selectedDate],
    queryFn: () => api.signals(selectedDate!),
    enabled: !!selectedDate,
  });

  const report = useQuery({
    queryKey: ["report", selectedDate],
    queryFn: () => api.report(selectedDate!),
    enabled: !!selectedDate && viewReport,
  });

  // Auto-select latest date
  const effectiveDate = selectedDate ?? dates.data?.[0] ?? null;
  if (!selectedDate && dates.data?.[0]) {
    setSelectedDate(dates.data[0]);
  }

  const sortedSignals = [...(signals.data ?? [])].sort(compareSignalsForDisplay);

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Signals</h2>

      {/* Date selector */}
      <div className="flex items-center gap-4">
        <select
          value={effectiveDate ?? ""}
          onChange={(e) => {
            setSelectedDate(e.target.value);
            setViewReport(false);
          }}
          className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm"
        >
          {(dates.data ?? []).map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        <button
          onClick={() => setViewReport(!viewReport)}
          className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded text-sm"
        >
          {viewReport ? "Show Signals" : "Show Report"}
        </button>
      </div>

      {/* Signals table */}
      {!viewReport && signals.data && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b border-gray-800">
                <th className="py-2 px-3">Ticker</th>
                <th className="py-2 px-3">Name</th>
                <th className="py-2 px-3">Action</th>
                <th className="py-2 px-3">Execution</th>
                <th className="py-2 px-3">Momentum</th>
                <th className="py-2 px-3">Price</th>
                <th className="py-2 px-3">Intent</th>
                <th className="py-2 px-3">Order</th>
                <th className="py-2 px-3">Plan</th>
                <th className="py-2 px-3">Trigger</th>
                <th className="py-2 px-3">Period</th>
                <th className="py-2 px-3">Reason</th>
              </tr>
            </thead>
            <tbody>
              {sortedSignals.map((s, i) => {
                const executableBuy = getExecutableBuy(s);
                const executableSell = getExecutableSell(s);
                const momentumRank = getMomentumRank(s);
                const momentumValue = getMomentumValue(s);
                const sellIntent = getSellIntent(s);
                const sellOrder = getSellOrderLabel(s);
                const sellPlan = getSellPlanLabel(s);
                const sellTrigger = getSellTriggerLabel(s);
                const sellPeriod = getSellPeriodLabel(s);

                let rowClassName = "border-b border-gray-800/50 hover:bg-gray-800/30";
                if (executableSell) {
                  rowClassName = "border-b border-red-900/60 bg-red-950/20 hover:bg-red-950/30";
                } else if (executableBuy) {
                  rowClassName = "border-b border-emerald-900/60 bg-emerald-950/20 hover:bg-emerald-950/30";
                }

                return (
                <tr
                  key={i}
                  className={rowClassName}
                >
                  <td className="py-2 px-3 font-medium">
                    <Link
                      to={`/stock/${s.ticker}`}
                      className="text-blue-400 hover:underline"
                    >
                      {(s.ticker as string) ?? ""}
                    </Link>
                  </td>
                  <td className="py-2 px-3 text-gray-400 text-xs">
                    {names[String(s.ticker ?? "")] ?? ""}
                  </td>
                  <td className="py-2 px-3">
                    <span
                      className={
                        s.signal_type === "BUY"
                          ? "text-green-400 font-medium"
                          : s.signal_type === "SELL"
                            ? "text-red-400 font-medium"
                            : "text-gray-500"
                      }
                    >
                      {getDisplayAction(s)}
                    </span>
                  </td>
                  <td className="py-2 px-3">
                    <span
                      className={
                        executableSell
                          ? "rounded bg-red-500/15 px-2 py-1 text-xs font-medium text-red-300"
                          : executableBuy
                            ? "rounded bg-emerald-500/15 px-2 py-1 text-xs font-medium text-emerald-300"
                            : "text-gray-500 text-xs"
                      }
                    >
                      {getExecutionLabel(s)}
                    </span>
                  </td>
                  <td className="py-2 px-3 text-xs">
                    {momentumValue !== null
                      ? `#${momentumRank ?? "-"} / ${momentumValue >= 0 ? "+" : ""}${momentumValue.toFixed(2)}`
                      : "—"}
                  </td>
                  <td className="py-2 px-3">
                    {s.current_price
                      ? `¥${Number(s.current_price).toLocaleString()}`
                      : "—"}
                  </td>
                  <td className="py-2 px-3 text-xs text-gray-300">
                    {sellIntent}
                  </td>
                  <td className="py-2 px-3 text-xs text-gray-300">
                    {sellOrder}
                  </td>
                  <td className="py-2 px-3 text-xs text-gray-400 max-w-[180px] truncate">
                    {sellPlan}
                  </td>
                  <td className="py-2 px-3 text-xs text-gray-400 max-w-[180px] truncate">
                    {sellTrigger}
                  </td>
                  <td className="py-2 px-3 text-xs text-gray-300">
                    {sellPeriod}
                  </td>
                  <td className="py-2 px-3 text-xs text-gray-500 truncate max-w-sm">
                    {(s.reason as string) ?? ""}
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Report markdown */}
      {viewReport && report.data && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
          <pre className="text-gray-300 text-xs whitespace-pre-wrap font-mono max-h-[600px] overflow-y-auto">
            {report.data.content}
          </pre>
        </div>
      )}
    </div>
  );
}

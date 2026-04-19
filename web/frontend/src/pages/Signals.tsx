import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
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
                <th className="py-2 px-3">Confidence</th>
                <th className="py-2 px-3">Score</th>
                <th className="py-2 px-3">Price</th>
                <th className="py-2 px-3">Strategy</th>
                <th className="py-2 px-3">Reason</th>
              </tr>
            </thead>
            <tbody>
              {signals.data.map((s, i) => (
                <tr
                  key={i}
                  className="border-b border-gray-800/50 hover:bg-gray-800/30"
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
                        s.action === "BUY"
                          ? "text-green-400 font-medium"
                          : s.action === "SELL"
                            ? "text-red-400 font-medium"
                            : "text-gray-500"
                      }
                    >
                      {(s.action as string) ?? (s.signal_type as string) ?? ""}
                    </span>
                  </td>
                  <td className="py-2 px-3">
                    {Number(s.confidence ?? 0).toFixed(2)}
                  </td>
                  <td className="py-2 px-3">{Number(s.score ?? 0).toFixed(1)}</td>
                  <td className="py-2 px-3">
                    {s.current_price
                      ? `¥${Number(s.current_price).toLocaleString()}`
                      : "—"}
                  </td>
                  <td className="py-2 px-3 text-xs text-gray-400">
                    {(s.strategy_name as string) ?? ""}
                  </td>
                  <td className="py-2 px-3 text-xs text-gray-500 truncate max-w-xs">
                    {(s.reason as string) ?? ""}
                  </td>
                </tr>
              ))}
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

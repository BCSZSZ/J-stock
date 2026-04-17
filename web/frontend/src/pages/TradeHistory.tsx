import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useTickerNames } from "../hooks/useTickerNames";

export default function TradeHistory() {
  const { data, isLoading } = useQuery({
    queryKey: ["trade-history"],
    queryFn: api.tradeHistory,
  });
  const names = useTickerNames();
  const [filterTicker, setFilterTicker] = useState("");
  const [filterAction, setFilterAction] = useState<"" | "BUY" | "SELL">("");

  const allEvents: Array<Record<string, unknown>> =
    ((data as Record<string, unknown>)?.events as Array<Record<string, unknown>>) ?? [];

  const events = useMemo(() => {
    let filtered = allEvents;
    if (filterTicker) {
      filtered = filtered.filter((e) =>
        String(e.ticker ?? "").includes(filterTicker),
      );
    }
    if (filterAction) {
      filtered = filtered.filter((e) => e.action === filterAction);
    }
    return filtered;
  }, [allEvents, filterTicker, filterAction]);

  /** Extract entry_price from position_effects for SELL events, compute P&L */
  function getPnL(e: Record<string, unknown>): { entryPrice: number; pnl: number; pnlPct: number } | null {
    if (e.action !== "SELL") return null;
    const effects = e.position_effects as Array<Record<string, unknown>> | undefined;
    if (!effects || effects.length === 0) return null;
    // Weighted average entry price across all consumed lots
    let totalCost = 0;
    let totalQty = 0;
    for (const eff of effects) {
      const ep = Number(eff.entry_price ?? 0);
      const cq = Number(eff.consumed_quantity ?? 0);
      if (ep > 0 && cq > 0) { totalCost += ep * cq; totalQty += cq; }
    }
    if (totalQty === 0) return null;
    const entryPrice = totalCost / totalQty;
    const sellPrice = Number(e.price ?? 0);
    const qty = Number(e.qty ?? e.quantity ?? 0);
    const pnl = (sellPrice - entryPrice) * qty;
    const pnlPct = ((sellPrice - entryPrice) / entryPrice) * 100;
    return { entryPrice, pnl, pnlPct };
  }

  if (isLoading) return <div className="text-gray-500">Loading...</div>;

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Trade History</h2>

      {/* Filters */}
      <div className="flex gap-3 items-center">
        <input
          value={filterTicker}
          onChange={(e) => setFilterTicker(e.target.value)}
          placeholder="Filter by ticker..."
          className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm w-32"
        />
        <select
          value={filterAction}
          onChange={(e) => setFilterAction(e.target.value as "" | "BUY" | "SELL")}
          className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm"
        >
          <option value="">All Actions</option>
          <option value="BUY">BUY</option>
          <option value="SELL">SELL</option>
        </select>
        <span className="text-xs text-gray-500">
          {events.length} / {allEvents.length} events
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 border-b border-gray-800">
              <th className="py-2 px-3">Date</th>
              <th className="py-2 px-3">Ticker</th>
              <th className="py-2 px-3">Name</th>
              <th className="py-2 px-3">Action</th>
              <th className="py-2 px-3">Qty</th>
              <th className="py-2 px-3">Price</th>
              <th className="py-2 px-3">Entry Price</th>
              <th className="py-2 px-3">P&L</th>
              <th className="py-2 px-3">Reason</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e, i) => {
              const pnlInfo = getPnL(e);
              return (
              <tr
                key={i}
                className="border-b border-gray-800/50 hover:bg-gray-800/30"
              >
                <td className="py-2 px-3 text-gray-300">
                  {(e.date as string) ?? ""}
                </td>
                <td className="py-2 px-3 font-medium">
                  <Link
                    to={`/stock/${e.ticker}`}
                    className="text-blue-400 hover:underline"
                  >
                    {(e.ticker as string) ?? ""}
                  </Link>
                </td>
                <td className="py-2 px-3 text-gray-400 text-xs">
                  {names[String(e.ticker ?? "")] ?? ""}
                </td>
                <td className="py-2 px-3">
                  <span
                    className={
                      e.action === "BUY"
                        ? "text-green-400"
                        : e.action === "SELL"
                          ? "text-red-400"
                          : "text-gray-400"
                    }
                  >
                    {(e.action as string) ?? ""}
                  </span>
                </td>
                <td className="py-2 px-3">{String(e.qty ?? e.quantity ?? "")}</td>
                <td className="py-2 px-3">
                  ¥{Number(e.price ?? 0).toLocaleString()}
                </td>
                <td className="py-2 px-3 text-gray-400">
                  {pnlInfo ? `¥${pnlInfo.entryPrice.toLocaleString()}` : "—"}
                </td>
                <td className="py-2 px-3">
                  {pnlInfo ? (
                    <span className={pnlInfo.pnl >= 0 ? "text-green-400" : "text-red-400"}>
                      ¥{pnlInfo.pnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                      <span className="text-xs ml-1">
                        ({pnlInfo.pnlPct >= 0 ? "+" : ""}{pnlInfo.pnlPct.toFixed(1)}%)
                      </span>
                    </span>
                  ) : "—"}
                </td>
                <td className="py-2 px-3 text-gray-500 text-xs truncate max-w-xs">
                  {(e.reason as string) ?? (e.entry_reason as string) ?? ""}
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

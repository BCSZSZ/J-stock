import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  api,
  type TradeHistoryEvent,
  type TradeHistoryResponse,
} from "../api/client";
import { useTickerNames } from "../hooks/useTickerNames";

type SortKey =
  | "date"
  | "ticker"
  | "name"
  | "action"
  | "qty"
  | "price"
  | "open"
  | "errorJpy"
  | "errorPct"
  | "slippage"
  | "pnl";
type SortDir = "asc" | "desc";

function isActiveTradeEvent(event: TradeHistoryEvent): boolean {
  return String(event.status ?? "ACTIVE") === "ACTIVE";
}

function formatPrice(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "N/A";
  return `¥${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function formatSignedCurrency(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "N/A";
  const sign = value > 0 ? "+" : "";
  return `${sign}¥${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function formatSignedPercent(
  value: number | null | undefined,
  digits = 2,
): string {
  if (value == null || Number.isNaN(value)) return "N/A";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

function metricClass(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "text-gray-500";
  if (value > 0) return "text-red-400";
  if (value < 0) return "text-green-400";
  return "text-gray-300";
}

function compareNullableNumbers(
  left: number | null | undefined,
  right: number | null | undefined,
  dir: SortDir,
): number {
  const leftMissing = left == null || Number.isNaN(left);
  const rightMissing = right == null || Number.isNaN(right);
  if (leftMissing && rightMissing) return 0;
  if (leftMissing) return 1;
  if (rightMissing) return -1;
  return dir === "asc" ? left - right : right - left;
}

function compareStrings(left: string, right: string, dir: SortDir): number {
  const cmp = left.localeCompare(right);
  return dir === "asc" ? cmp : -cmp;
}

export default function TradeHistory() {
  const { data, isLoading } = useQuery({
    queryKey: ["trade-history"],
    queryFn: api.tradeHistory,
  });
  const names = useTickerNames();
  const [filterTicker, setFilterTicker] = useState("");
  const [filterAction, setFilterAction] = useState<"" | "BUY" | "SELL">("");
  const [sortKey, setSortKey] = useState<SortKey>("date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const tradeHistory = data as TradeHistoryResponse | undefined;
  const allEvents = tradeHistory?.events ?? [];
  const summary = tradeHistory?.summary;
  const effectiveEvents = useMemo(
    () => allEvents.filter(isActiveTradeEvent),
    [allEvents],
  );

  /** Extract entry_price from position_effects for SELL events, compute P&L */
  function getPnL(
    e: TradeHistoryEvent,
  ): { entryPrice: number; pnl: number; pnlPct: number } | null {
    if (e.action !== "SELL") return null;
    const effects = e.position_effects as TradeHistoryEvent[] | undefined;
    if (!effects || effects.length === 0) return null;
    let totalCost = 0;
    let totalQty = 0;
    for (const eff of effects) {
      const ep = Number(eff.entry_price ?? 0);
      const cq = Number(eff.consumed_quantity ?? 0);
      if (ep > 0 && cq > 0) {
        totalCost += ep * cq;
        totalQty += cq;
      }
    }
    if (totalQty === 0) return null;
    const entryPrice = totalCost / totalQty;
    const sellPrice = Number(e.price ?? 0);
    const qty = Number(e.quantity ?? 0);
    const pnl = (sellPrice - entryPrice) * qty;
    const pnlPct = ((sellPrice - entryPrice) / entryPrice) * 100;
    return { entryPrice, pnl, pnlPct };
  }

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir(key === "date" ? "desc" : "asc");
    }
  }

  function sortIndicator(key: SortKey) {
    if (sortKey !== key) return "";
    return sortDir === "asc" ? " ▲" : " ▼";
  }

  const events = useMemo(() => {
    let filtered = effectiveEvents;
    if (filterTicker) {
      filtered = filtered.filter((e) =>
        String(e.ticker ?? "").includes(filterTicker),
      );
    }
    if (filterAction) {
      filtered = filtered.filter((e) => e.action === filterAction);
    }

    const sorted = [...filtered].sort((a, b) => {
      switch (sortKey) {
        case "date":
          return compareStrings(String(a.date ?? ""), String(b.date ?? ""), sortDir);
        case "ticker":
          return compareStrings(String(a.ticker ?? ""), String(b.ticker ?? ""), sortDir);
        case "name":
          return compareStrings(
            names[String(a.ticker ?? "")] ?? "",
            names[String(b.ticker ?? "")] ?? "",
            sortDir,
          );
        case "action":
          return compareStrings(String(a.action ?? ""), String(b.action ?? ""), sortDir);
        case "qty":
          return compareNullableNumbers(a.quantity, b.quantity, sortDir);
        case "price":
          return compareNullableNumbers(a.price, b.price, sortDir);
        case "open":
          return compareNullableNumbers(
            a.execution_open_price,
            b.execution_open_price,
            sortDir,
          );
        case "errorJpy":
          return compareNullableNumbers(
            a.actual_vs_open_jpy,
            b.actual_vs_open_jpy,
            sortDir,
          );
        case "errorPct":
          return compareNullableNumbers(
            a.actual_vs_open_pct,
            b.actual_vs_open_pct,
            sortDir,
          );
        case "slippage":
          return compareNullableNumbers(a.slippage_pct, b.slippage_pct, sortDir);
        case "pnl": {
          return compareNullableNumbers(getPnL(a)?.pnl, getPnL(b)?.pnl, sortDir);
        }
      }
    });
    return sorted;
  }, [effectiveEvents, filterTicker, filterAction, sortKey, sortDir, names]);

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
          {events.length} / {effectiveEvents.length} events
        </span>
      </div>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
          <div className="text-xs uppercase tracking-wide text-gray-500">Benchmarked Trades</div>
          <div className="mt-2 text-2xl font-semibold">
            {(summary?.benchmarked_trades ?? 0).toLocaleString()} / {(summary?.total_trades ?? 0).toLocaleString()}
          </div>
          <div className="mt-1 text-xs text-gray-500">Execution-day open resolved</div>
        </div>
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
          <div className="text-xs uppercase tracking-wide text-gray-500">Capital-weighted Overall</div>
          <div className={`mt-2 text-2xl font-semibold ${metricClass(summary?.capital_weighted_avg_slippage_pct_overall)}`}>
            {formatSignedPercent(summary?.capital_weighted_avg_slippage_pct_overall)}
          </div>
          <div className="mt-1 text-xs text-gray-500">Weighted by execution-day open notional</div>
        </div>
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
          <div className="text-xs uppercase tracking-wide text-gray-500">Capital-weighted BUY</div>
          <div className={`mt-2 text-2xl font-semibold ${metricClass(summary?.capital_weighted_avg_slippage_pct_buy)}`}>
            {formatSignedPercent(summary?.capital_weighted_avg_slippage_pct_buy)}
          </div>
          <div className="mt-1 text-xs text-gray-500">Positive means worse than open</div>
        </div>
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
          <div className="text-xs uppercase tracking-wide text-gray-500">Capital-weighted SELL</div>
          <div className={`mt-2 text-2xl font-semibold ${metricClass(summary?.capital_weighted_avg_slippage_pct_sell)}`}>
            {formatSignedPercent(summary?.capital_weighted_avg_slippage_pct_sell)}
          </div>
          <div className="mt-1 text-xs text-gray-500">Positive means worse than open</div>
        </div>
      </section>

      <div className="flex flex-wrap gap-x-4 gap-y-2 text-xs text-gray-500">
        <span>
          Coverage {(summary?.benchmarked_trades ?? 0).toLocaleString()} / {(summary?.total_trades ?? 0).toLocaleString()}
        </span>
        <span>
          Equal-weight Overall {formatSignedPercent(summary?.avg_slippage_pct_overall)}
        </span>
        <span>
          Equal-weight BUY {formatSignedPercent(summary?.avg_slippage_pct_buy)}
        </span>
        <span>
          Equal-weight SELL {formatSignedPercent(summary?.avg_slippage_pct_sell)}
        </span>
        <span>
          Median {formatSignedPercent(summary?.median_slippage_pct)}
        </span>
        <span>
          Avg Absolute Error {formatPrice(summary?.avg_abs_error_jpy)}
        </span>
        <span>
          Missing Open {(summary?.missing_open_trades ?? 0).toLocaleString()}
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 border-b border-gray-800">
              <th className="py-2 px-3 cursor-pointer select-none hover:text-gray-300" onClick={() => toggleSort("date")}>Date{sortIndicator("date")}</th>
              <th className="py-2 px-3 cursor-pointer select-none hover:text-gray-300" onClick={() => toggleSort("ticker")}>Ticker{sortIndicator("ticker")}</th>
              <th className="py-2 px-3 cursor-pointer select-none hover:text-gray-300" onClick={() => toggleSort("name")}>Name{sortIndicator("name")}</th>
              <th className="py-2 px-3 cursor-pointer select-none hover:text-gray-300" onClick={() => toggleSort("action")}>Action{sortIndicator("action")}</th>
              <th className="py-2 px-3 cursor-pointer select-none hover:text-gray-300" onClick={() => toggleSort("qty")}>Qty{sortIndicator("qty")}</th>
              <th className="py-2 px-3 cursor-pointer select-none hover:text-gray-300" onClick={() => toggleSort("price")}>Price{sortIndicator("price")}</th>
              <th className="py-2 px-3 cursor-pointer select-none hover:text-gray-300" onClick={() => toggleSort("open")}>Open{sortIndicator("open")}</th>
              <th className="py-2 px-3 cursor-pointer select-none hover:text-gray-300" onClick={() => toggleSort("errorJpy")}>Error JPY{sortIndicator("errorJpy")}</th>
              <th className="py-2 px-3 cursor-pointer select-none hover:text-gray-300" onClick={() => toggleSort("errorPct")}>Error %{sortIndicator("errorPct")}</th>
              <th className="py-2 px-3 cursor-pointer select-none hover:text-gray-300" onClick={() => toggleSort("slippage")}>Slippage{sortIndicator("slippage")}</th>
              <th className="py-2 px-3">Entry Price</th>
              <th className="py-2 px-3 cursor-pointer select-none hover:text-gray-300" onClick={() => toggleSort("pnl")}>P&L{sortIndicator("pnl")}</th>
              <th className="py-2 px-3">Reason</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e, i) => {
              const pnlInfo = getPnL(e);
              const benchmarkAvailable = e.benchmark_status === "AVAILABLE";
              return (
              <tr
                key={String(e.event_id ?? `${e.date}-${e.ticker}-${e.action}-${i}`)}
                className="border-b border-gray-800/50 hover:bg-gray-800/30"
              >
                <td className="py-2 px-3 text-gray-300">
                  {e.date ?? ""}
                </td>
                <td className="py-2 px-3 font-medium">
                  <Link
                    to={`/stock/${e.ticker}`}
                    className="text-blue-400 hover:underline"
                  >
                    {e.ticker ?? ""}
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
                    {e.action ?? ""}
                  </span>
                </td>
                <td className="py-2 px-3">{String(e.quantity ?? "")}</td>
                <td className="py-2 px-3">{formatPrice(e.price)}</td>
                <td className="py-2 px-3 text-gray-300">
                  {benchmarkAvailable ? formatPrice(e.execution_open_price) : (
                    <span className="text-gray-500" title={String(e.benchmark_status ?? "")}>N/A</span>
                  )}
                </td>
                <td className={`py-2 px-3 ${metricClass(e.slippage_pct)}`}>
                  {benchmarkAvailable ? formatSignedCurrency(e.actual_vs_open_jpy) : (
                    <span className="text-gray-500" title={String(e.benchmark_status ?? "")}>N/A</span>
                  )}
                </td>
                <td className={`py-2 px-3 ${metricClass(e.slippage_pct)}`}>
                  {benchmarkAvailable ? formatSignedPercent(e.actual_vs_open_pct) : (
                    <span className="text-gray-500" title={String(e.benchmark_status ?? "")}>N/A</span>
                  )}
                </td>
                <td className={`py-2 px-3 ${metricClass(e.slippage_pct)}`}>
                  {benchmarkAvailable ? formatSignedPercent(e.slippage_pct) : (
                    <span className="text-gray-500" title={String(e.benchmark_status ?? "")}>N/A</span>
                  )}
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
                  {String(e.reason ?? e.entry_reason ?? "")}
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

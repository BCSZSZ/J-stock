import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useConfirmDialog } from "../components/ConfirmDialog";
import LogOutput from "../components/LogOutput";
import { useStreamExec } from "../hooks/useStreamExec";
import { api, type StockPoolOption } from "../api/client";
import {
  compareSignalsForDisplay,
  getExecutionQuantity,
  getNormalizedTradeAction,
} from "../signalSemantics";
import { useTickerNames } from "../hooks/useTickerNames";

interface TradeRow {
  ticker: string;
  action: "BUY" | "SELL";
  quantity: string;
  price: string;
  date: string;
}

interface ProductionOptionsResponse {
  production: {
    monitor_list_file: string;
    sector_pool_file: string;
    stock_pool_catalog_file: string;
  };
  defaults: {
    pool_id: string;
  };
  stock_pools: StockPoolOption[];
}

const emptyTrade = (): TradeRow => ({
  ticker: "",
  action: "BUY",
  quantity: "",
  price: "",
  date: new Date().toISOString().slice(0, 10),
});

function formatStockPoolAtrRange(pool: StockPoolOption): string | null {
  if (pool.atr_ratio_min == null && pool.atr_ratio_max == null) {
    return null;
  }

  const minLabel =
    pool.atr_ratio_min == null ? "-" : `${(pool.atr_ratio_min * 100).toFixed(1)}%`;
  const maxLabel =
    pool.atr_ratio_max == null ? "-" : `${(pool.atr_ratio_max * 100).toFixed(1)}%`;
  return `${minLabel} - ${maxLabel}`;
}

function formatStockPoolLabel(pool: StockPoolOption): string {
  const atrRange = formatStockPoolAtrRange(pool);
  return atrRange ? `${pool.label} (${atrRange})` : pool.label;
}

export default function Production() {
  const daily = useStreamExec();
  const fetchData = useStreamExec();
  const universe = useStreamExec();
  const priceCheck = useStreamExec();
  const inputTrades = useStreamExec();
  const { confirm, dialog } = useConfirmDialog();
  const [trades, setTrades] = useState<TradeRow[]>([emptyTrade()]);
  const [selectedPoolId, setSelectedPoolId] = useState("");
  const names = useTickerNames();
  const options = useQuery<ProductionOptionsResponse>({
    queryKey: ["production-options"],
    queryFn: api.productionOptions,
  });
  const stockPools = options.data?.stock_pools ?? [];
  const selectedPool = stockPools.find((pool) => pool.id === selectedPoolId) ?? null;
  const effectiveMonitorListFile =
    selectedPool?.monitor_list_file ?? options.data?.production.monitor_list_file ?? "";
  const effectiveSectorPoolFile =
    selectedPool?.sector_pool_file ?? options.data?.production.sector_pool_file ?? "";

  useEffect(() => {
    if (!options.data) {
      return;
    }
    const defaultPoolId = options.data.defaults.pool_id ?? "";
    setSelectedPoolId((current) => current || defaultPoolId);
  }, [options.data]);

  // Signal import
  const signalDates = useQuery({ queryKey: ["signal-dates"], queryFn: api.signalDates });
  const [importDate, setImportDate] = useState<string | null>(null);
  const effectiveImportDate = importDate ?? signalDates.data?.[0] ?? null;
  if (!importDate && signalDates.data?.[0]) {
    setImportDate(signalDates.data[0]);
  }

  /** Get the next JPX trading day after a given date (via backend API). */
  async function fetchNextTradingDay(dateStr: string): Promise<string> {
    try {
      const res = await api.nextTradingDay(dateStr);
      return res.date;
    } catch {
      // Fallback: skip weekends only
      const d = new Date(dateStr + "T00:00:00");
      do { d.setDate(d.getDate() + 1); } while (d.getDay() === 0 || d.getDay() === 6);
      return d.toISOString().slice(0, 10);
    }
  }

  async function handleImportFromSignals() {
    if (!effectiveImportDate) return;
    const [signals, tradeDate] = await Promise.all([
      api.signals(effectiveImportDate),
      fetchNextTradingDay(effectiveImportDate),
    ]);
    const newRows: TradeRow[] = [...signals]
      .sort(compareSignalsForDisplay)
      .map((s) => {
        const action = getNormalizedTradeAction(s);
        const qtyNum = getExecutionQuantity(s);
        if (action === null) {
          return null;
        }
        return {
          ticker: String(s.ticker ?? ""),
          action,
          quantity: qtyNum > 0 ? String(qtyNum) : "",
          price: "",
          date: tradeDate,
          _qtyNum: qtyNum,
        } as TradeRow & { _qtyNum: number };
      })
      .filter((row): row is TradeRow & { _qtyNum: number } => row !== null)
      // Only import actually-executable trades (qty > 0). Skip rows like
      // "max positions reached" BUYs or HOLD-recommended SELLs which the
      // backend report records with qty=0.
      .filter((r) => (r as TradeRow & { _qtyNum: number })._qtyNum > 0)
      .map(({ _qtyNum, ...rest }: any) => rest as TradeRow);
    if (newRows.length === 0) return;
    setTrades(newRows);
  }

  async function handleDaily(noFetch: boolean) {
    const ok = await confirm(
      "Run Production Daily",
      [
        `Execute production --daily${noFetch ? " --no-fetch" : ""}? This will generate signals and reports.`,
        `Stock Pool: ${selectedPool ? formatStockPoolLabel(selectedPool) : "production default"}`,
      ].join("\n"),
    );
    if (!ok) return;
    daily.execute("/production/daily", {
      confirm: true,
      no_fetch: noFetch,
      pool_id: selectedPoolId || undefined,
    });
  }

  async function handleFetch() {
    const ok = await confirm(
      "Fetch Data",
      "Fetch latest data for all monitor list tickers from J-Quants API?",
    );
    if (!ok) return;
    fetchData.execute("/production/fetch", { confirm: true });
  }

  async function handleUniverse() {
    const ok = await confirm(
      "Run Universe Selection",
      "Run sector universe selection (--no-fetch --resume)?",
    );
    if (!ok) return;
    universe.execute("/production/universe", { confirm: true });
  }

  async function handleCheckPrice(scope: "all" | "today") {
    const label = scope === "all" ? "Check All Price" : "Check Today";
    const detail =
      scope === "all"
        ? "Scan all active lots and repair fallback signal_entry_price anchors using entry-date open prices?"
        : "Scan today's active lots and repair fallback signal_entry_price anchors using entry-date open prices?";
    const ok = await confirm(label, detail);
    if (!ok) return;
    const path =
      scope === "all"
        ? "/production/check-price-all"
        : "/production/check-price-today";
    priceCheck.execute(path, { confirm: true });
  }

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Production</h2>
      {dialog}

      {options.isError && (
        <div className="rounded-lg border border-red-800 bg-red-950/40 px-4 py-3 text-sm text-red-200">
          Failed to load production options: {String(options.error)}
        </div>
      )}

      {/* Action buttons */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-3">
          <h3 className="font-semibold text-blue-400">Daily Workflow</h3>
          <p className="text-xs text-gray-500">
            Fetch data, generate signals, produce report
          </p>
          <div className="rounded border border-gray-800 bg-gray-950/40 p-3 space-y-2">
            <div className="text-[11px] uppercase tracking-wide text-gray-500">
              Optional Stock Pool Override
            </div>
            <select
              value={selectedPoolId}
              onChange={(e) => setSelectedPoolId(e.target.value)}
              className="w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm"
            >
              <option value="">Use current production defaults</option>
              {stockPools.map((pool) => (
                <option key={pool.id} value={pool.id} disabled={!pool.enabled}>
                  {formatStockPoolLabel(pool)}
                </option>
              ))}
            </select>
            <div className="text-xs text-gray-400 break-all">
              Monitor: {effectiveMonitorListFile || "Not configured"}
            </div>
            <div className="text-xs text-gray-500 break-all">
              Sector Pool: {effectiveSectorPoolFile || "Not configured"}
            </div>
            <div className="text-xs text-gray-500 break-all">
              Catalog: {options.data?.production.stock_pool_catalog_file || "Not configured"}
            </div>
            <div className="text-[11px] text-gray-500">
              Leave this empty to preserve the current production daily behavior. This override applies only to Daily and Daily (no-fetch) in phase 1.
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => handleDaily(false)}
              disabled={daily.running}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded text-sm"
            >
              Run Daily
            </button>
            <button
              onClick={() => handleDaily(true)}
              disabled={daily.running}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 disabled:opacity-50 rounded text-sm"
            >
              Run Daily (no-fetch)
            </button>
          </div>
          {daily.lines.length > 0 && (
            <LogOutput
              lines={daily.lines}
              running={daily.running}
              exitCode={daily.exitCode}
            />
          )}
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-3">
          <h3 className="font-semibold text-green-400">Data & Universe</h3>
          <div className="flex gap-2">
            <button
              onClick={handleFetch}
              disabled={fetchData.running}
              className="px-4 py-2 bg-green-700 hover:bg-green-600 disabled:opacity-50 rounded text-sm"
            >
              Fetch Data
            </button>
            <button
              onClick={handleUniverse}
              disabled={universe.running}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 disabled:opacity-50 rounded text-sm"
            >
              Universe Selection
            </button>
            <button
              onClick={() => handleCheckPrice("all")}
              disabled={priceCheck.running}
              className="px-4 py-2 bg-amber-700 hover:bg-amber-600 disabled:opacity-50 rounded text-sm"
            >
              Check All Price
            </button>
            <button
              onClick={() => handleCheckPrice("today")}
              disabled={priceCheck.running}
              className="px-4 py-2 bg-amber-900 hover:bg-amber-800 disabled:opacity-50 rounded text-sm"
            >
              Check Today
            </button>
          </div>
          {fetchData.lines.length > 0 && (
            <LogOutput
              lines={fetchData.lines}
              running={fetchData.running}
              exitCode={fetchData.exitCode}
            />
          )}
          {universe.lines.length > 0 && (
            <LogOutput
              lines={universe.lines}
              running={universe.running}
              exitCode={universe.exitCode}
            />
          )}
          {priceCheck.lines.length > 0 && (
            <LogOutput
              lines={priceCheck.lines}
              running={priceCheck.running}
              exitCode={priceCheck.exitCode}
            />
          )}
        </div>
      </div>

      {/* Input Trades */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-3">
        <h3 className="font-semibold text-yellow-400">Input Trades</h3>
        <p className="text-xs text-gray-500">
          Record executed BUY/SELL trades (equivalent to production --input
          --manual)
        </p>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">Import from signals:</span>
          <select
            value={effectiveImportDate ?? ""}
            onChange={(e) => setImportDate(e.target.value)}
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs"
          >
            {(signalDates.data ?? []).map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
          <button
            onClick={handleImportFromSignals}
            disabled={!effectiveImportDate}
            className="px-3 py-1 bg-yellow-700 hover:bg-yellow-600 disabled:opacity-50 rounded text-xs"
          >
            Import
          </button>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-left border-b border-gray-800">
              <th className="py-1 px-2">Ticker</th>
              <th className="py-1 px-2">Name</th>
              <th className="py-1 px-2">Action</th>
              <th className="py-1 px-2">Qty</th>
              <th className="py-1 px-2">Price</th>
              <th className="py-1 px-2">Date</th>
              <th className="py-1 px-2 w-10"></th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t, i) => (
              <tr key={i}>
                <td className="py-1 px-2">
                  <input
                    value={t.ticker}
                    onChange={(e) => {
                      const next = [...trades];
                      next[i] = { ...t, ticker: e.target.value };
                      setTrades(next);
                    }}
                    className="w-24 bg-gray-800 border border-gray-700 rounded px-2 py-1"
                    placeholder="e.g. 7182"
                  />
                </td>
                <td className="py-1 px-2 text-gray-400 text-xs">
                  {names[t.ticker] ?? ""}
                </td>
                <td className="py-1 px-2">
                  <select
                    value={t.action}
                    onChange={(e) => {
                      const next = [...trades];
                      next[i] = {
                        ...t,
                        action: e.target.value as "BUY" | "SELL",
                      };
                      setTrades(next);
                    }}
                    className="bg-gray-800 border border-gray-700 rounded px-2 py-1"
                  >
                    <option>BUY</option>
                    <option>SELL</option>
                  </select>
                </td>
                <td className="py-1 px-2">
                  <input
                    value={t.quantity}
                    onChange={(e) => {
                      const next = [...trades];
                      next[i] = { ...t, quantity: e.target.value };
                      setTrades(next);
                    }}
                    type="number"
                    className="w-20 bg-gray-800 border border-gray-700 rounded px-2 py-1"
                    placeholder="100"
                  />
                </td>
                <td className="py-1 px-2">
                  <input
                    value={t.price}
                    onChange={(e) => {
                      const next = [...trades];
                      next[i] = { ...t, price: e.target.value };
                      setTrades(next);
                    }}
                    type="number"
                    className="w-28 bg-gray-800 border border-gray-700 rounded px-2 py-1"
                    placeholder="2500"
                  />
                </td>
                <td className="py-1 px-2">
                  <input
                    value={t.date}
                    onChange={(e) => {
                      const next = [...trades];
                      next[i] = { ...t, date: e.target.value };
                      setTrades(next);
                    }}
                    type="date"
                    className="bg-gray-800 border border-gray-700 rounded px-2 py-1"
                  />
                </td>
                <td className="py-1 px-2">
                  {trades.length > 1 && (
                    <button
                      onClick={() =>
                        setTrades(trades.filter((_, j) => j !== i))
                      }
                      className="text-red-400 hover:text-red-300 text-xs"
                    >
                      ✕
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="flex gap-2">
          <button
            onClick={() => setTrades([...trades, emptyTrade()])}
            className="px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-xs"
          >
            + Add Row
          </button>
          <button
            onClick={async () => {
              const valid = trades.filter(
                (t) =>
                  t.ticker && t.quantity && t.price && Number(t.quantity) > 0,
              );
              if (valid.length === 0) return;
              const ok = await confirm(
                "Submit Trades",
                `Submit ${valid.length} trade(s)? This will modify production state.`,
              );
              if (!ok) return;
              inputTrades.execute("/production/input-trades", {
                confirm: true,
                aws_profile: "personal",
                trades: valid.map((t) => ({
                  ticker: t.ticker,
                  action: t.action,
                  quantity: Number(t.quantity),
                  price: Number(t.price),
                  date: t.date,
                })),
              });
            }}
            disabled={inputTrades.running}
            className="px-4 py-1 bg-yellow-600 hover:bg-yellow-500 disabled:opacity-50 rounded text-xs font-medium"
          >
            Submit Trades
          </button>
        </div>
        {inputTrades.lines.length > 0 && (
          <LogOutput
            lines={inputTrades.lines}
            running={inputTrades.running}
            exitCode={inputTrades.exitCode}
          />
        )}
      </div>
    </div>
  );
}

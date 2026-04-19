import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useConfirmDialog } from "../components/ConfirmDialog";
import LogOutput from "../components/LogOutput";
import { useStreamExec } from "../hooks/useStreamExec";
import { api } from "../api/client";
import { useTickerNames } from "../hooks/useTickerNames";

interface TradeRow {
  ticker: string;
  action: "BUY" | "SELL";
  quantity: string;
  price: string;
  date: string;
}

const emptyTrade = (): TradeRow => ({
  ticker: "",
  action: "BUY",
  quantity: "",
  price: "",
  date: new Date().toISOString().slice(0, 10),
});

export default function Production() {
  const daily = useStreamExec();
  const fetchData = useStreamExec();
  const universe = useStreamExec();
  const inputTrades = useStreamExec();
  const { confirm, dialog } = useConfirmDialog();
  const [trades, setTrades] = useState<TradeRow[]>([emptyTrade()]);
  const names = useTickerNames();

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
    const newRows: TradeRow[] = signals
      .filter((s) => s.action === "BUY" || s.action === "SELL")
      .map((s) => {
        const action = String(s.action) as "BUY" | "SELL";
        const qty = action === "SELL"
          ? String(s.planned_sell_qty ?? s.position_qty ?? "")
          : String(s.suggested_qty ?? "");
        return {
          ticker: String(s.ticker ?? ""),
          action,
          quantity: qty,
          price: "",
          date: tradeDate,
        };
      });
    if (newRows.length === 0) return;
    setTrades(newRows);
  }

  async function handleDaily(noFetch: boolean) {
    const ok = await confirm(
      "Run Production Daily",
      `Execute production --daily${noFetch ? " --no-fetch" : ""}? This will generate signals and reports.`,
    );
    if (!ok) return;
    daily.execute("/production/daily", { confirm: true, no_fetch: noFetch });
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

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Production</h2>
      {dialog}

      {/* Action buttons */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-3">
          <h3 className="font-semibold text-blue-400">Daily Workflow</h3>
          <p className="text-xs text-gray-500">
            Fetch data, generate signals, produce report
          </p>
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

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useConfirmDialog } from "../components/ConfirmDialog";
import LogOutput from "../components/LogOutput";
import { useStreamExec } from "../hooks/useStreamExec";
import {
  api,
  type IndustryFilterMode,
  type InputTradeImportPreviewResponse,
  type MomentumExhaustionMode,
  type StockPoolOption,
} from "../api/client";
import { useTickerNames } from "../hooks/useTickerNames";

interface TradeRow {
  ticker: string;
  action: "BUY" | "SELL";
  quantity: string;
  price: string;
  date: string;
}

type PositionSizingMode = "fixed" | "atr";

interface ProductionOptionsResponse {
  production: {
    monitor_list_file: string;
    sector_pool_file: string;
    stock_pool_catalog_file: string;
  };
  defaults: {
    pool_id: string;
    position_sizing_mode: string;
    risk_per_trade_pct: number;
    atr_stop_multiple: number;
    atr_ratio_min: number | null;
    atr_ratio_max: number | null;
    momentum_exhaustion_mode: MomentumExhaustionMode;
    momentum_exhaustion_max_score: number;
    momentum_exhaustion_threshold_method: "absolute";
    industry_filter_mode: IndustryFilterMode;
    max_buy_per_industry_per_day: number;
    max_total_positions_per_industry: number;
    industry_reference_file: string;
  };
  stock_pools: StockPoolOption[];
}

interface ImportSummary {
  signalDate: string;
  tradeDate: string;
  latestCsvFile: string | null;
  latestCsvMtime: string | null;
  matchedCount: number;
  csvOnlyCount: number;
  signalOnlyCount: number;
  mode: string;
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

function parseOptionalFloat(value: string): number | undefined {
  const normalized = value.trim();
  if (!normalized) return undefined;
  const parsed = Number.parseFloat(normalized);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function parseOptionalInt(value: string): number | undefined {
  const normalized = value.trim();
  if (!normalized) return undefined;
  const parsed = Number.parseInt(normalized, 10);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function isPositionSizingMode(value: string): value is PositionSizingMode {
  return value === "fixed" || value === "atr";
}

function formatTradeNumber(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) {
    return "";
  }
  return value.toFixed(6).replace(/\.?0+$/, "");
}

function previewToTradeRows(preview: InputTradeImportPreviewResponse): TradeRow[] {
  return preview.rows.map((row) => ({
    ticker: row.ticker,
    action: row.action === "SELL" ? "SELL" : "BUY",
    quantity: String(row.quantity),
    price: formatTradeNumber(row.price),
    date: row.date,
  }));
}

function formatImportMode(mode: string): string {
  return mode === "csv_authoritative" ? "CSV authoritative" : "Signal fallback";
}

function formatImportFileLabel(path: string | null): string {
  if (!path) {
    return "No CSV file";
  }
  const segments = path.split(/[\\/]/);
  return segments[segments.length - 1] || path;
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
  const [positionSizingMode, setPositionSizingMode] =
    useState<PositionSizingMode>("fixed");
  const [riskPerTradePct, setRiskPerTradePct] = useState("0.0078");
  const [atrStopMultiple, setAtrStopMultiple] = useState("1.0");
  const [atrRatioMin, setAtrRatioMin] = useState("");
  const [atrRatioMax, setAtrRatioMax] = useState("");
  const [momentumExhaustionMode, setMomentumExhaustionMode] =
    useState<MomentumExhaustionMode>("shadow");
  const [momentumExhaustionMaxScore, setMomentumExhaustionMaxScore] =
    useState("4.0");
  const [industryFilterMode, setIndustryFilterMode] =
    useState<IndustryFilterMode>("enforce");
  const [maxBuyPerIndustryPerDay, setMaxBuyPerIndustryPerDay] = useState("1");
  const [maxTotalPositionsPerIndustry, setMaxTotalPositionsPerIndustry] =
    useState("3");
  const [industryReferenceFile, setIndustryReferenceFile] =
    useState("data/jpx_final_list.csv");
  const [importingTrades, setImportingTrades] = useState(false);
  const [importWarnings, setImportWarnings] = useState<string[]>([]);
  const [importError, setImportError] = useState<string | null>(null);
  const [importSummary, setImportSummary] = useState<ImportSummary | null>(null);
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
  const parsedRiskPerTradePct = parseOptionalFloat(riskPerTradePct);
  const parsedAtrStopMultiple = parseOptionalFloat(atrStopMultiple);
  const parsedAtrRatioMin = parseOptionalFloat(atrRatioMin);
  const parsedAtrRatioMax = parseOptionalFloat(atrRatioMax);
  const parsedMomentumExhaustionMaxScore = parseOptionalFloat(
    momentumExhaustionMaxScore,
  );
  const parsedMaxBuyPerIndustryPerDay = parseOptionalInt(maxBuyPerIndustryPerDay);
  const parsedMaxTotalPositionsPerIndustry = parseOptionalInt(
    maxTotalPositionsPerIndustry,
  );
  const atrSizingRuntimeEnabled = positionSizingMode === "atr";
  const riskPerTradeInvalid =
    atrSizingRuntimeEnabled &&
    (parsedRiskPerTradePct === undefined || parsedRiskPerTradePct <= 0);
  const atrStopMultipleInvalid =
    atrSizingRuntimeEnabled &&
    (parsedAtrStopMultiple === undefined || parsedAtrStopMultiple <= 0);
  const atrRatioRangeInvalid =
    parsedAtrRatioMin !== undefined &&
    parsedAtrRatioMax !== undefined &&
    parsedAtrRatioMin > parsedAtrRatioMax;
  const atrRatioMinInvalid =
    atrRatioMin.trim() !== "" &&
    (parsedAtrRatioMin === undefined || parsedAtrRatioMin < 0);
  const atrRatioMaxInvalid =
    atrRatioMax.trim() !== "" &&
    (parsedAtrRatioMax === undefined || parsedAtrRatioMax <= 0);
  const atrRuntimeInvalid =
    riskPerTradeInvalid ||
    atrStopMultipleInvalid ||
    atrRatioMinInvalid ||
    atrRatioMaxInvalid ||
    atrRatioRangeInvalid;
  const industryFilterInvalid =
    (maxBuyPerIndustryPerDay.trim() !== "" &&
      (parsedMaxBuyPerIndustryPerDay === undefined ||
        parsedMaxBuyPerIndustryPerDay <= 0)) ||
    (maxTotalPositionsPerIndustry.trim() !== "" &&
      (parsedMaxTotalPositionsPerIndustry === undefined ||
        parsedMaxTotalPositionsPerIndustry <= 0));

  useEffect(() => {
    if (!options.data) {
      return;
    }
    const defaultPoolId = options.data.defaults.pool_id ?? "";
    setSelectedPoolId((current) => current || defaultPoolId);
    setPositionSizingMode((current) =>
      current !== "fixed"
        ? current
        : isPositionSizingMode(options.data.defaults.position_sizing_mode)
          ? options.data.defaults.position_sizing_mode
          : "fixed",
    );
    setRiskPerTradePct(String(options.data.defaults.risk_per_trade_pct ?? 0.0078));
    setAtrStopMultiple(String(options.data.defaults.atr_stop_multiple ?? 1.0));
    setAtrRatioMin(
      options.data.defaults.atr_ratio_min !== null &&
        options.data.defaults.atr_ratio_min !== undefined
        ? String(options.data.defaults.atr_ratio_min)
        : "",
    );
    setAtrRatioMax(
      options.data.defaults.atr_ratio_max !== null &&
        options.data.defaults.atr_ratio_max !== undefined
        ? String(options.data.defaults.atr_ratio_max)
        : "",
    );
    setMomentumExhaustionMode(
      options.data.defaults.momentum_exhaustion_mode ?? "shadow",
    );
    setMomentumExhaustionMaxScore(
      String(options.data.defaults.momentum_exhaustion_max_score ?? 4.0),
    );
    setIndustryFilterMode(options.data.defaults.industry_filter_mode ?? "enforce");
    setMaxBuyPerIndustryPerDay(
      String(options.data.defaults.max_buy_per_industry_per_day ?? 1),
    );
    setMaxTotalPositionsPerIndustry(
      String(options.data.defaults.max_total_positions_per_industry ?? 3),
    );
    setIndustryReferenceFile(
      options.data.defaults.industry_reference_file ?? "data/jpx_final_list.csv",
    );
  }, [options.data]);

  // Signal import
  const signalDates = useQuery({ queryKey: ["signal-dates"], queryFn: api.signalDates });
  const [importDate, setImportDate] = useState<string | null>(null);
  const effectiveImportDate = importDate ?? signalDates.data?.[0] ?? null;
  if (!importDate && signalDates.data?.[0]) {
    setImportDate(signalDates.data[0]);
  }

  async function handleImportFromSignals() {
    if (!effectiveImportDate || importingTrades) return;
    setImportingTrades(true);
    setImportError(null);
    try {
      const preview = await api.inputTradeImportPreview(effectiveImportDate);
      const newRows = previewToTradeRows(preview);
      setTrades(
        newRows.length > 0
          ? newRows
          : [{ ...emptyTrade(), date: preview.trade_date }],
      );
      setImportWarnings(preview.warnings);
      setImportSummary({
        signalDate: preview.signal_date,
        tradeDate: preview.trade_date,
        latestCsvFile: preview.latest_csv_file,
        latestCsvMtime: preview.latest_csv_mtime,
        matchedCount: preview.matched_count,
        csvOnlyCount: preview.csv_only_count,
        signalOnlyCount: preview.signal_only_count,
        mode: preview.mode,
      });
    } catch (error) {
      setImportError(error instanceof Error ? error.message : String(error));
    } finally {
      setImportingTrades(false);
    }
  }

  async function handleDaily(noFetch: boolean) {
    if (atrRuntimeInvalid || industryFilterInvalid) {
      return;
    }
    const normalizedAtrRatioMin =
      atrRatioMin.trim() === "" ? null : parsedAtrRatioMin;
    const normalizedAtrRatioMax =
      atrRatioMax.trim() === "" ? null : parsedAtrRatioMax;
    const ok = await confirm(
      "Run Production Daily",
      [
        `Execute production --daily${noFetch ? " --no-fetch" : ""}? This will generate signals and reports.`,
        `Stock Pool: ${selectedPool ? formatStockPoolLabel(selectedPool) : "production default"}`,
        atrSizingRuntimeEnabled
          ? `Position Sizing: ${positionSizingMode} | risk ${parsedRiskPerTradePct} | stop ${parsedAtrStopMultiple} ATR`
          : `Position Sizing: ${positionSizingMode} (ATR runtime parameters ignored)`,
        `ATR% Filter Bounds: ${normalizedAtrRatioMin ?? "-"} - ${normalizedAtrRatioMax ?? "-"}`,
        `Momentum Exhaustion: ${momentumExhaustionMode} | max score ${parsedMomentumExhaustionMaxScore ?? "config default"}`,
        `Industry Filter: ${industryFilterMode} | daily ${parsedMaxBuyPerIndustryPerDay ?? "config default"} | total ${parsedMaxTotalPositionsPerIndustry ?? "config default"}`,
      ].join("\n"),
    );
    if (!ok) return;
    daily.execute("/production/daily", {
      confirm: true,
      no_fetch: noFetch,
      pool_id: selectedPoolId || undefined,
      position_sizing_mode: positionSizingMode,
      risk_per_trade_pct: atrSizingRuntimeEnabled ? parsedRiskPerTradePct : undefined,
      atr_stop_multiple: atrSizingRuntimeEnabled ? parsedAtrStopMultiple : undefined,
      atr_ratio_min: normalizedAtrRatioMin,
      atr_ratio_max: normalizedAtrRatioMax,
      momentum_exhaustion_mode: momentumExhaustionMode,
      momentum_exhaustion_max_score: parsedMomentumExhaustionMaxScore,
      momentum_exhaustion_threshold_method: "absolute",
      industry_filter_mode: industryFilterMode,
      max_buy_per_industry_per_day: parsedMaxBuyPerIndustryPerDay,
      max_total_positions_per_industry: parsedMaxTotalPositionsPerIndustry,
      industry_reference_file: industryReferenceFile.trim() || undefined,
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
          <div className="rounded border border-gray-800 bg-gray-950/40 p-3 space-y-3">
            <div className="text-[11px] uppercase tracking-wide text-gray-500">
              ATR Runtime Parameters
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-1 text-xs text-gray-400">
                <span>Position Sizing</span>
                <select
                  value={positionSizingMode}
                  onChange={(e) => setPositionSizingMode(e.target.value as PositionSizingMode)}
                  className="h-10 w-full rounded border border-gray-700 bg-gray-800 px-3 text-sm text-gray-100"
                >
                  <option value="fixed">fixed</option>
                  <option value="atr">atr</option>
                </select>
              </label>
              <label className="space-y-1 text-xs text-gray-400">
                <span>Risk Per Trade</span>
                <input
                  value={riskPerTradePct}
                  onChange={(e) => setRiskPerTradePct(e.target.value)}
                  disabled={!atrSizingRuntimeEnabled}
                  className="h-10 w-full rounded border border-gray-700 bg-gray-800 px-3 text-sm text-gray-100 disabled:cursor-not-allowed disabled:bg-gray-900 disabled:text-gray-500"
                />
              </label>
              <label className="space-y-1 text-xs text-gray-400">
                <span>ATR Stop Multiple</span>
                <input
                  value={atrStopMultiple}
                  onChange={(e) => setAtrStopMultiple(e.target.value)}
                  disabled={!atrSizingRuntimeEnabled}
                  className="h-10 w-full rounded border border-gray-700 bg-gray-800 px-3 text-sm text-gray-100 disabled:cursor-not-allowed disabled:bg-gray-900 disabled:text-gray-500"
                />
              </label>
              <label className="space-y-1 text-xs text-gray-400">
                <span>ATR% Min</span>
                <input
                  value={atrRatioMin}
                  onChange={(e) => setAtrRatioMin(e.target.value)}
                  className="h-10 w-full rounded border border-gray-700 bg-gray-800 px-3 text-sm text-gray-100"
                />
              </label>
              <label className="space-y-1 text-xs text-gray-400">
                <span>ATR% Max</span>
                <input
                  value={atrRatioMax}
                  onChange={(e) => setAtrRatioMax(e.target.value)}
                  className="h-10 w-full rounded border border-gray-700 bg-gray-800 px-3 text-sm text-gray-100"
                />
              </label>
            </div>
            {!atrSizingRuntimeEnabled && (
              <p className="text-xs text-gray-500">
                Risk and stop settings are only applied when Position Sizing is set to atr.
              </p>
            )}
            {atrRuntimeInvalid && (
              <p className="text-xs text-red-400">
                Risk and stop multiple must be positive, ATR% values must be valid, and ATR% min must be no greater than max.
              </p>
            )}
          </div>
          <div className="rounded border border-gray-800 bg-gray-950/40 p-3 space-y-3">
            <div className="text-[11px] uppercase tracking-wide text-gray-500">
              Momentum Exhaustion
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-1 text-xs text-gray-400">
                <span>Mode</span>
                <select
                  value={momentumExhaustionMode}
                  onChange={(e) =>
                    setMomentumExhaustionMode(e.target.value as MomentumExhaustionMode)
                  }
                  className="h-10 w-full rounded border border-gray-700 bg-gray-800 px-3 text-sm text-gray-100"
                >
                  <option value="shadow">shadow</option>
                  <option value="enforce">enforce</option>
                  <option value="off">off</option>
                </select>
              </label>
              <label className="space-y-1 text-xs text-gray-400">
                <span>Max Score</span>
                <input
                  value={momentumExhaustionMaxScore}
                  onChange={(e) => setMomentumExhaustionMaxScore(e.target.value)}
                  className="h-10 w-full rounded border border-gray-700 bg-gray-800 px-3 text-sm text-gray-100"
                />
              </label>
            </div>
          </div>
          <div className="rounded border border-gray-800 bg-gray-950/40 p-3 space-y-3">
            <div className="text-[11px] uppercase tracking-wide text-gray-500">
              Industry Filter
            </div>
            <div className="grid gap-3 sm:grid-cols-4">
              <label className="space-y-1 text-xs text-gray-400">
                <span>Mode</span>
                <select
                  value={industryFilterMode}
                  onChange={(e) =>
                    setIndustryFilterMode(e.target.value as IndustryFilterMode)
                  }
                  className="h-10 w-full rounded border border-gray-700 bg-gray-800 px-3 text-sm text-gray-100"
                >
                  <option value="enforce">enforce</option>
                  <option value="shadow">shadow</option>
                  <option value="off">off</option>
                </select>
              </label>
              <label className="space-y-1 text-xs text-gray-400">
                <span>Daily Buy Cap</span>
                <input
                  value={maxBuyPerIndustryPerDay}
                  onChange={(e) => setMaxBuyPerIndustryPerDay(e.target.value)}
                  className="h-10 w-full rounded border border-gray-700 bg-gray-800 px-3 text-sm text-gray-100"
                />
              </label>
              <label className="space-y-1 text-xs text-gray-400">
                <span>Total Position Cap</span>
                <input
                  value={maxTotalPositionsPerIndustry}
                  onChange={(e) => setMaxTotalPositionsPerIndustry(e.target.value)}
                  className="h-10 w-full rounded border border-gray-700 bg-gray-800 px-3 text-sm text-gray-100"
                />
              </label>
              <label className="space-y-1 text-xs text-gray-400">
                <span>Reference CSV</span>
                <input
                  value={industryReferenceFile}
                  onChange={(e) => setIndustryReferenceFile(e.target.value)}
                  className="h-10 w-full rounded border border-gray-700 bg-gray-800 px-3 text-sm text-gray-100"
                />
              </label>
            </div>
            {industryFilterInvalid && (
              <p className="text-xs text-red-400">
                Industry caps must be positive integers.
              </p>
            )}
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => handleDaily(false)}
              disabled={daily.running || atrRuntimeInvalid || industryFilterInvalid}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded text-sm"
            >
              Run Daily
            </button>
            <button
              onClick={() => handleDaily(true)}
              disabled={daily.running || atrRuntimeInvalid || industryFilterInvalid}
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
            disabled={!effectiveImportDate || importingTrades}
            className="px-3 py-1 bg-yellow-700 hover:bg-yellow-600 disabled:opacity-50 rounded text-xs"
          >
            {importingTrades ? "Importing..." : "Import"}
          </button>
        </div>
        {importError ? (
          <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            Failed to import trades: {importError}
          </div>
        ) : null}
        {importSummary ? (
          <div className="rounded-lg border border-gray-800 bg-gray-950/40 px-4 py-3 text-xs text-gray-300">
            <div className="font-medium text-gray-100">Latest import summary</div>
            <div className="mt-2 space-y-1">
              <div>
                Signal date {importSummary.signalDate}{" -> "}trade date {importSummary.tradeDate}
              </div>
              <div>
                Mode: {formatImportMode(importSummary.mode)} | matched {importSummary.matchedCount} | csv-only {importSummary.csvOnlyCount} | signal-only {importSummary.signalOnlyCount}
              </div>
              <div className="break-all text-gray-400">
                CSV: {formatImportFileLabel(importSummary.latestCsvFile)}
                {importSummary.latestCsvMtime ? ` (${importSummary.latestCsvMtime})` : ""}
              </div>
            </div>
          </div>
        ) : null}
        {importWarnings.length > 0 ? (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
            <div className="font-medium">Imported with warnings</div>
            <ul className="mt-2 space-y-1 text-xs text-amber-100/80">
              {importWarnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </div>
        ) : null}
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

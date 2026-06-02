import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  api,
  type EntrySignalAnalysisDatasetDetail,
  type EntrySignalAnalysisDatasetSummary,
  type EntrySignalAnalysisOptions,
  type EntrySignalAnalysisRunRequest,
} from "../api/client";
import StrategyMultiSelect from "../components/StrategyMultiSelect";
import LogOutput from "../components/LogOutput";
import { useStreamExec } from "../hooks/useStreamExec";

const cardClassName = "rounded-lg border border-gray-800 bg-gray-950/40 p-4";
const inputClassName = "h-10 w-full rounded border border-gray-700 bg-gray-800 px-3 text-sm";
const labelClassName = "mb-2 block text-xs uppercase tracking-wide text-gray-500";

function parseIntegerList(value: string): number[] {
  return value
    .split(/[\n,\s]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => Number.parseInt(item, 10))
    .filter((item) => Number.isFinite(item) && item > 0);
}

function parseStringList(value: string): string[] {
  return value
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseOptionalNumber(value: string): number | null {
  const normalized = value.trim();
  if (!normalized) return null;
  const parsed = Number.parseFloat(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function metricValue(
  overall: Record<string, unknown> | undefined,
  key: string,
): Record<string, unknown> | null {
  const value = overall?.[key];
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : null;
}

export default function EntrySignalAnalysis() {
  const exec = useStreamExec();
  const options = useQuery<EntrySignalAnalysisOptions>({
    queryKey: ["entry-signal-analysis-options"],
    queryFn: api.entrySignalAnalysisOptions,
  });

  const [initialized, setInitialized] = useState(false);
  const [selectedEntry, setSelectedEntry] = useState<string[]>([]);
  const [universeFiles, setUniverseFiles] = useState("");
  const [years, setYears] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [horizons, setHorizons] = useState("1,3,5");
  const [primaryHorizon, setPrimaryHorizon] = useState("5");
  const [labelMode, setLabelMode] = useState<"signal_close" | "next_open">("next_open");
  const [rankingStrategy, setRankingStrategy] = useState("momentum");
  const [entryFilterMode, setEntryFilterMode] = useState<"auto" | "off" | "atr" | "single" | "grid">("auto");
  const [entryFilterNames, setEntryFilterNames] = useState("");
  const [positionSizingMode, setPositionSizingMode] = useState<"fixed" | "atr">("atr");
  const [riskPerTradePct, setRiskPerTradePct] = useState("0.0078");
  const [atrStopMultiple, setAtrStopMultiple] = useState("1.0");
  const [atrRatioMin, setAtrRatioMin] = useState("");
  const [atrRatioMax, setAtrRatioMax] = useState("");
  const [tailGuardEnabled, setTailGuardEnabled] = useState(true);
  const [tailGuardMaxRank, setTailGuardMaxRank] = useState("12");
  const [limit, setLimit] = useState("");
  const [dataRoot, setDataRoot] = useState("data");
  const [outputDir, setOutputDir] = useState("");
  const [selectedDataset, setSelectedDataset] = useState("");

  const datasets = useQuery<EntrySignalAnalysisDatasetSummary[]>({
    queryKey: ["entry-signal-analysis-datasets", outputDir],
    queryFn: () => api.entrySignalAnalysisDatasets(outputDir.trim() || undefined),
  });
  const datasetSummary = useQuery<EntrySignalAnalysisDatasetDetail>({
    queryKey: ["entry-signal-analysis-summary", selectedDataset, outputDir],
    queryFn: () =>
      api.entrySignalAnalysisDatasetSummary(
        selectedDataset,
        outputDir.trim() || undefined,
      ),
    enabled: Boolean(selectedDataset),
  });

  useEffect(() => {
    if (!options.data || initialized) return;
    const defaults = options.data.defaults;
    setSelectedEntry(defaults.entry_strategies ?? []);
    setUniverseFiles((defaults.universe_files ?? []).join("\n"));
    setHorizons((defaults.horizons ?? [1, 3, 5]).join(","));
    setPrimaryHorizon(String(defaults.primary_horizon ?? 5));
    setLabelMode((defaults.label_mode as "signal_close" | "next_open") ?? "next_open");
    setRankingStrategy(defaults.ranking_strategy ?? "momentum");
    setEntryFilterMode(
      (defaults.entry_filter_mode as "auto" | "off" | "atr" | "single" | "grid") ??
        "auto",
    );
    setEntryFilterNames((defaults.entry_filter_names ?? []).join(","));
    setPositionSizingMode((defaults.position_sizing_mode as "fixed" | "atr") ?? "atr");
    setRiskPerTradePct(String(defaults.risk_per_trade_pct ?? 0.0078));
    setAtrStopMultiple(String(defaults.atr_stop_multiple ?? 1.0));
    setAtrRatioMin(defaults.atr_ratio_min == null ? "" : String(defaults.atr_ratio_min));
    setAtrRatioMax(defaults.atr_ratio_max == null ? "" : String(defaults.atr_ratio_max));
    setTailGuardEnabled(Boolean(defaults.tail_guard_enabled));
    setTailGuardMaxRank(String(defaults.tail_guard_max_rank ?? 12));
    setDataRoot(defaults.data_root ?? "data");
    setOutputDir(defaults.output_dir ?? "entry_signal_analysis");
    setInitialized(true);
  }, [initialized, options.data]);

  useEffect(() => {
    if (exec.exitCode === 0) {
      void datasets.refetch();
    }
  }, [datasets, exec.exitCode]);

  useEffect(() => {
    if (!selectedDataset && datasets.data && datasets.data.length > 0) {
      setSelectedDataset(datasets.data[0]?.id ?? "");
    }
  }, [datasets.data, selectedDataset]);

  const summary = datasetSummary.data?.summary;
  const overall = useMemo(() => {
    const value = summary?.overall;
    return typeof value === "object" && value !== null
      ? (value as Record<string, unknown>)
      : undefined;
  }, [summary]);
  const oneDay = useMemo(() => metricValue(overall, "1d"), [overall]);
  const threeDay = useMemo(() => metricValue(overall, "3d"), [overall]);
  const fiveDay = useMemo(() => metricValue(overall, "5d"), [overall]);

  function handleRun() {
    const parsedYears = parseIntegerList(years);
    const body: EntrySignalAnalysisRunRequest = {
      entry_strategies: selectedEntry,
      universe_files: parseStringList(universeFiles),
      years: parsedYears.length > 0 ? parsedYears : undefined,
      start: parsedYears.length > 0 ? undefined : start.trim() || undefined,
      end: parsedYears.length > 0 ? undefined : end.trim() || undefined,
      horizons: parseIntegerList(horizons),
      primary_horizon: Number.parseInt(primaryHorizon, 10) || 5,
      label_mode: labelMode,
      ranking_strategy: rankingStrategy.trim() || undefined,
      entry_filter_mode: entryFilterMode,
      entry_filter_names: parseStringList(entryFilterNames),
      position_sizing_mode: positionSizingMode,
      risk_per_trade_pct: parseOptionalNumber(riskPerTradePct),
      atr_stop_multiple: parseOptionalNumber(atrStopMultiple),
      atr_ratio_min: parseOptionalNumber(atrRatioMin),
      atr_ratio_max: parseOptionalNumber(atrRatioMax),
      tail_guard_enabled: tailGuardEnabled,
      tail_guard_max_rank: parseOptionalNumber(tailGuardMaxRank),
      limit: parseOptionalNumber(limit),
      data_root: dataRoot.trim() || "data",
      output_dir: outputDir.trim() || undefined,
    };
    void exec.execute("/entry-signal-analysis/run", body as Record<string, unknown>);
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <h2 className="text-2xl font-bold">Entry Signal Analysis</h2>
          <p className="text-sm text-gray-500">
            Production-style daily signal quality analysis without portfolio or cash constraints.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void datasets.refetch()}
          className="h-9 rounded border border-gray-700 px-3 text-sm hover:bg-gray-800"
        >
          Refresh Datasets
        </button>
      </div>

      {options.isError && (
        <div className="rounded-lg border border-red-800 bg-red-950/40 px-4 py-3 text-sm text-red-200">
          Failed to load options: {String(options.error)}
        </div>
      )}

      <section className={`${cardClassName} space-y-4`}>
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          <div className="xl:col-span-2">
            <StrategyMultiSelect
              label="Entry Strategies"
              options={options.data?.entry_strategies ?? []}
              selected={selectedEntry}
              onChange={setSelectedEntry}
              searchPlaceholder="Search entry strategies..."
            />
          </div>
          <div className={cardClassName}>
            <label className={labelClassName}>Universe Files</label>
            <textarea
              value={universeFiles}
              onChange={(e) => setUniverseFiles(e.target.value)}
              className="min-h-[160px] w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
          <div className={cardClassName}>
            <label className={labelClassName}>Years</label>
            <input value={years} onChange={(e) => setYears(e.target.value)} className={inputClassName} placeholder="2024 2025" />
          </div>
          <div className={cardClassName}>
            <label className={labelClassName}>Date Range</label>
            <div className="space-y-2">
              <input value={start} onChange={(e) => setStart(e.target.value)} placeholder="YYYY-MM-DD" className={inputClassName} />
              <input value={end} onChange={(e) => setEnd(e.target.value)} placeholder="YYYY-MM-DD" className={inputClassName} />
            </div>
          </div>
          <div className={cardClassName}>
            <label className={labelClassName}>Horizons / Primary</label>
            <div className="space-y-2">
              <input value={horizons} onChange={(e) => setHorizons(e.target.value)} className={inputClassName} />
              <input value={primaryHorizon} onChange={(e) => setPrimaryHorizon(e.target.value)} className={inputClassName} />
            </div>
          </div>
          <div className={cardClassName}>
            <label className={labelClassName}>Label / Ranking</label>
            <div className="space-y-2">
              <select
                value={labelMode}
                onChange={(e) => setLabelMode(e.target.value as "signal_close" | "next_open")}
                className={inputClassName}
              >
                {(options.data?.label_modes ?? ["signal_close", "next_open"]).map((mode) => (
                  <option key={mode} value={mode}>
                    {mode}
                  </option>
                ))}
              </select>
              <input value={rankingStrategy} onChange={(e) => setRankingStrategy(e.target.value)} className={inputClassName} />
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
          <div className={cardClassName}>
            <label className={labelClassName}>Entry Filter</label>
            <div className="space-y-2">
              <select
                value={entryFilterMode}
                onChange={(e) =>
                  setEntryFilterMode(
                    e.target.value as "auto" | "off" | "atr" | "single" | "grid",
                  )
                }
                className={inputClassName}
              >
                {(options.data?.entry_filter_modes ?? ["auto", "off", "atr", "single", "grid"]).map(
                  (mode) => (
                    <option key={mode} value={mode}>
                      {mode}
                    </option>
                  ),
                )}
              </select>
              <input
                value={entryFilterNames}
                onChange={(e) => setEntryFilterNames(e.target.value)}
                placeholder="variant names, comma separated"
                className={inputClassName}
              />
            </div>
          </div>
          <div className={cardClassName}>
            <label className={labelClassName}>ATR Runtime</label>
            <div className="space-y-2">
              <input value={riskPerTradePct} onChange={(e) => setRiskPerTradePct(e.target.value)} placeholder="risk_per_trade_pct" className={inputClassName} />
              <input value={atrStopMultiple} onChange={(e) => setAtrStopMultiple(e.target.value)} placeholder="atr_stop_multiple" className={inputClassName} />
            </div>
          </div>
          <div className={cardClassName}>
            <label className={labelClassName}>ATR Bounds</label>
            <div className="space-y-2">
              <input value={atrRatioMin} onChange={(e) => setAtrRatioMin(e.target.value)} placeholder="atr_ratio_min" className={inputClassName} />
              <input value={atrRatioMax} onChange={(e) => setAtrRatioMax(e.target.value)} placeholder="atr_ratio_max" className={inputClassName} />
            </div>
          </div>
          <div className={cardClassName}>
            <label className={labelClassName}>Tail Guard</label>
            <div className="space-y-2 text-sm text-gray-300">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={tailGuardEnabled}
                  onChange={(e) => setTailGuardEnabled(e.target.checked)}
                />
                Enabled
              </label>
              <input value={tailGuardMaxRank} onChange={(e) => setTailGuardMaxRank(e.target.value)} placeholder="max rank" className={inputClassName} />
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className={cardClassName}>
            <label className={labelClassName}>Position Sizing</label>
            <select
              value={positionSizingMode}
              onChange={(e) => setPositionSizingMode(e.target.value as "fixed" | "atr")}
              className={inputClassName}
            >
              <option value="fixed">fixed</option>
              <option value="atr">atr</option>
            </select>
          </div>
          <div className={cardClassName}>
            <label className={labelClassName}>Data Root / Limit</label>
            <div className="space-y-2">
              <input value={dataRoot} onChange={(e) => setDataRoot(e.target.value)} className={inputClassName} />
              <input value={limit} onChange={(e) => setLimit(e.target.value)} placeholder="limit" className={inputClassName} />
            </div>
          </div>
          <div className={cardClassName}>
            <label className={labelClassName}>Output Dir</label>
            <input value={outputDir} onChange={(e) => setOutputDir(e.target.value)} className={inputClassName} />
          </div>
        </div>

        <div className="flex justify-end">
          <button
            type="button"
            onClick={handleRun}
            className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500"
          >
            Run Entry Signal Analysis
          </button>
        </div>
      </section>

      <section className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className={`${cardClassName} xl:col-span-1`}>
          <h3 className="mb-3 font-semibold text-blue-400">Datasets</h3>
          <div className="space-y-2 max-h-[420px] overflow-y-auto">
            {(datasets.data ?? []).map((dataset) => (
              <button
                key={dataset.id}
                type="button"
                onClick={() => setSelectedDataset(dataset.id)}
                className={`w-full rounded border px-3 py-3 text-left text-sm ${
                  selectedDataset === dataset.id
                    ? "border-blue-500 bg-blue-600/10"
                    : "border-gray-800 bg-gray-900/40 hover:bg-gray-900"
                }`}
              >
                <div className="font-medium text-gray-200">{dataset.dataset_id}</div>
                <div className="mt-1 text-xs text-gray-500">{dataset.generated_at}</div>
                <div className="mt-2 text-xs text-gray-400">
                  cand {dataset.candidate_count} / selected {dataset.selected_count}
                </div>
              </button>
            ))}
            {!datasets.isLoading && (datasets.data ?? []).length === 0 && (
              <div className="text-sm text-gray-500">No datasets found.</div>
            )}
          </div>
        </div>

        <div className={`${cardClassName} xl:col-span-2 space-y-4`}>
          <h3 className="font-semibold text-blue-400">Summary</h3>
          {datasetSummary.isLoading && (
            <div className="text-sm text-gray-400">Loading dataset summary...</div>
          )}
          {!datasetSummary.isLoading && !summary && (
            <div className="text-sm text-gray-500">Select a dataset to view summary.</div>
          )}
          {summary && (
            <>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className={cardClassName}>
                  <label className={labelClassName}>Counts</label>
                  <div className="space-y-1 text-sm text-gray-300">
                    <div>candidate_count: {String(summary.candidate_count ?? "-")}</div>
                    <div>selected_count: {String(summary.selected_count ?? "-")}</div>
                    <div>trading_day_count: {String(summary.trading_day_count ?? "-")}</div>
                  </div>
                </div>
                <div className={cardClassName}>
                  <label className={labelClassName}>1D</label>
                  <div className="space-y-1 text-sm text-gray-300">
                    <div>win_rate: {String(oneDay?.win_rate ?? "-")}</div>
                    <div>avg_return: {String(oneDay?.avg_return_pct ?? "-")}</div>
                    <div>median_return: {String(oneDay?.median_return_pct ?? "-")}</div>
                  </div>
                </div>
                <div className={cardClassName}>
                  <label className={labelClassName}>3D / 5D</label>
                  <div className="space-y-1 text-sm text-gray-300">
                    <div>3D win_rate: {String(threeDay?.win_rate ?? "-")}</div>
                    <div>3D avg_return: {String(threeDay?.avg_return_pct ?? "-")}</div>
                    <div>5D win_rate: {String(fiveDay?.win_rate ?? "-")}</div>
                    <div>5D avg_return: {String(fiveDay?.avg_return_pct ?? "-")}</div>
                  </div>
                </div>
              </div>

              <div className={cardClassName}>
                <label className={labelClassName}>Top Daily Windows</label>
                <pre className="overflow-x-auto whitespace-pre-wrap text-xs text-gray-300">
                  {JSON.stringify(summary.top_daily_windows ?? [], null, 2)}
                </pre>
              </div>
            </>
          )}
        </div>
      </section>

      <section className={cardClassName}>
        <h3 className="mb-3 font-semibold text-blue-400">Run Log</h3>
        <LogOutput lines={exec.lines} running={exec.running} exitCode={exec.exitCode} />
      </section>
    </div>
  );
}
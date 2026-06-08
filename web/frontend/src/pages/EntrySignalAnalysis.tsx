import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  api,
  type EntrySignalAnalysisDatasetDetail,
  type EntrySignalAnalysisDatasetSummary,
  type EntrySignalAnalysisHorizonStats,
  type EntrySignalAnalysisOptions,
  type EntrySignalAnalysisPrimaryHorizonValidation,
  type EntrySignalAnalysisPrimaryStrategyTailRobustnessRanking,
  type EntrySignalAnalysisPrimaryValidationSlice,
  type EntrySignalAnalysisRunRequest,
  type EntrySignalAnalysisTopDailyWindows,
  type MomentumExhaustionMode,
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

function formatRate(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return `${(value * 100).toFixed(2)}%`;
}

function formatPercent(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return `${value.toFixed(3)}%`;
}

function formatBooleanFlag(value: boolean | null | undefined): string {
  if (typeof value !== "boolean") return "-";
  return value ? "yes" : "no";
}

function metricFromUnknown(value: Record<string, unknown> | null): EntrySignalAnalysisHorizonStats | null {
  if (!value) return null;
  return value as EntrySignalAnalysisHorizonStats;
}

function sliceLabel(slice: EntrySignalAnalysisPrimaryValidationSlice): string {
  if (
    typeof slice.strength_min === "number" &&
    Number.isFinite(slice.strength_min) &&
    typeof slice.strength_max === "number" &&
    Number.isFinite(slice.strength_max)
  ) {
    return `${slice.group_label} [${slice.strength_min.toFixed(2)}, ${slice.strength_max.toFixed(2)}]`;
  }
  return slice.group_label;
}

function ValidationTable({
  title,
  slices,
}: {
  title: string;
  slices: EntrySignalAnalysisPrimaryValidationSlice[];
}) {
  return (
    <div className={cardClassName}>
      <label className={labelClassName}>{title}</label>
      {slices.length === 0 ? (
        <div className="text-sm text-gray-500">No validation rows.</div>
      ) : (
        <div className="max-h-[320px] overflow-auto rounded border border-gray-800">
          <table className="min-w-full text-left text-xs text-gray-300">
            <thead className="sticky top-0 bg-gray-950/95 text-gray-400">
              <tr>
                <th className="px-3 py-2">Group</th>
                <th className="px-3 py-2 text-right">Count</th>
                <th className="px-3 py-2 text-right">Win</th>
                <th className="px-3 py-2 text-right">Mean</th>
                <th className="px-3 py-2 text-right">Median</th>
                <th className="px-3 py-2 text-right">Mean&gt;Median</th>
                <th className="px-3 py-2 text-right">Avg Loss</th>
                <th className="px-3 py-2 text-right">P10</th>
                <th className="px-3 py-2 text-right">P50</th>
                <th className="px-3 py-2 text-right">P90</th>
              </tr>
            </thead>
            <tbody>
              {slices.map((slice) => (
                <tr key={slice.group_key} className="border-t border-gray-800 align-top">
                  <td className="px-3 py-2 font-medium text-gray-200">{sliceLabel(slice)}</td>
                  <td className="px-3 py-2 text-right">{String(slice.stats.count ?? "-")}</td>
                  <td className="px-3 py-2 text-right">{formatRate(slice.stats.win_rate)}</td>
                  <td className="px-3 py-2 text-right">{formatPercent(slice.stats.avg_return_pct)}</td>
                  <td className="px-3 py-2 text-right">{formatPercent(slice.stats.median_return_pct)}</td>
                  <td className="px-3 py-2 text-right">{formatBooleanFlag(slice.stats.mean_gt_median)}</td>
                  <td className="px-3 py-2 text-right">{formatPercent(slice.stats.avg_loss_pct)}</td>
                  <td className="px-3 py-2 text-right">{formatPercent(slice.stats.p10_return_pct)}</td>
                  <td className="px-3 py-2 text-right">{formatPercent(slice.stats.p50_return_pct)}</td>
                  <td className="px-3 py-2 text-right">{formatPercent(slice.stats.p90_return_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function TailRobustnessRankingTable({
  title,
  rankings,
}: {
  title: string;
  rankings: EntrySignalAnalysisPrimaryStrategyTailRobustnessRanking[];
}) {
  return (
    <div className={cardClassName}>
      <label className={labelClassName}>{title}</label>
      {rankings.length === 0 ? (
        <div className="text-sm text-gray-500">No ranking rows.</div>
      ) : (
        <div className="max-h-[360px] overflow-auto rounded border border-gray-800">
          <table className="min-w-full text-left text-xs text-gray-300">
            <thead className="sticky top-0 bg-gray-950/95 text-gray-400">
              <tr>
                <th className="px-3 py-2 text-right">Rank</th>
                <th className="px-3 py-2">Strategy</th>
                <th className="px-3 py-2">Filter</th>
                <th className="px-3 py-2 text-right">Trim5</th>
                <th className="px-3 py-2 text-right">Median</th>
                <th className="px-3 py-2 text-right">Top5</th>
                <th className="px-3 py-2 text-right">Net w/o Top5</th>
                <th className="px-3 py-2 text-right">P10</th>
                <th className="px-3 py-2 text-right">Avg Loss</th>
              </tr>
            </thead>
            <tbody>
              {rankings.map((ranking) => (
                <tr key={ranking.group_key} className="border-t border-gray-800 align-top">
                  <td className="px-3 py-2 text-right">{ranking.rank}</td>
                  <td className="px-3 py-2 font-medium text-gray-200">{ranking.entry_strategy}</td>
                  <td className="px-3 py-2">{ranking.entry_filter_name}</td>
                  <td className="px-3 py-2 text-right">{formatPercent(ranking.stats.trimmed_mean_5pct_return_pct)}</td>
                  <td className="px-3 py-2 text-right">{formatPercent(ranking.stats.median_return_pct)}</td>
                  <td className="px-3 py-2 text-right">{formatRate(ranking.stats.top_5pct_contribution_ratio)}</td>
                  <td className="px-3 py-2 text-right">{formatPercent(ranking.stats.net_without_top_5pct_return_pct)}</td>
                  <td className="px-3 py-2 text-right">{formatPercent(ranking.stats.p10_return_pct)}</td>
                  <td className="px-3 py-2 text-right">{formatPercent(ranking.stats.avg_loss_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
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
  const [primaryHorizons, setPrimaryHorizons] = useState("5");
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
  const [momentumExhaustionMode, setMomentumExhaustionMode] =
    useState<MomentumExhaustionMode>("enforce");
  const [momentumExhaustionMaxScore, setMomentumExhaustionMaxScore] =
    useState("4.0");
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
    setPrimaryHorizons(
      (defaults.primary_horizons && defaults.primary_horizons.length > 0
        ? defaults.primary_horizons
        : [defaults.primary_horizon ?? 5]
      ).join(","),
    );
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
    setMomentumExhaustionMode(defaults.momentum_exhaustion_mode ?? "enforce");
    setMomentumExhaustionMaxScore(
      String(defaults.momentum_exhaustion_max_score ?? 4.0),
    );
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
  const oneDay = useMemo(() => metricFromUnknown(metricValue(overall, "1d")), [overall]);
  const threeDay = useMemo(() => metricFromUnknown(metricValue(overall, "3d")), [overall]);
  const fiveDay = useMemo(() => metricFromUnknown(metricValue(overall, "5d")), [overall]);
  const primaryValidations = useMemo(() => {
    const values = summary?.primary_horizon_validations;
    if (Array.isArray(values) && values.length > 0) {
      return values;
    }
    const fallback = summary?.primary_horizon_validation;
    return fallback ? [fallback] : [];
  }, [summary]) as EntrySignalAnalysisPrimaryHorizonValidation[];
  const topDailyWindowsByHorizon = useMemo(() => {
    const values = summary?.top_daily_windows_by_horizon;
    if (Array.isArray(values) && values.length > 0) {
      return values;
    }
    const fallbackValidation = primaryValidations[0];
    const fallbackWindows = summary?.top_daily_windows;
    if (fallbackValidation && Array.isArray(fallbackWindows)) {
      return [
        {
          primary_horizon: fallbackValidation.primary_horizon,
          primary_horizon_label: fallbackValidation.primary_horizon_label,
          sort_column: `selected_${fallbackValidation.primary_horizon}d_avg_return_pct`,
          windows: fallbackWindows,
        },
      ];
    }
    return [];
  }, [primaryValidations, summary]) as EntrySignalAnalysisTopDailyWindows[];

  function handleRun() {
    const parsedYears = parseIntegerList(years);
    const parsedHorizons = parseIntegerList(horizons);
    const parsedPrimaryHorizons = parseIntegerList(primaryHorizons);
    const body: EntrySignalAnalysisRunRequest = {
      entry_strategies: selectedEntry,
      universe_files: parseStringList(universeFiles),
      years: parsedYears.length > 0 ? parsedYears : undefined,
      start: parsedYears.length > 0 ? undefined : start.trim() || undefined,
      end: parsedYears.length > 0 ? undefined : end.trim() || undefined,
      horizons: parsedHorizons,
      primary_horizons: parsedPrimaryHorizons,
      primary_horizon: parsedPrimaryHorizons[0] ?? parsedHorizons[0] ?? 5,
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
      momentum_exhaustion_mode: momentumExhaustionMode,
      momentum_exhaustion_max_score: parseOptionalNumber(momentumExhaustionMaxScore),
      momentum_exhaustion_threshold_method: "absolute",
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
            <label className={labelClassName}>Horizons / Detailed Horizons</label>
            <div className="space-y-2">
              <input value={horizons} onChange={(e) => setHorizons(e.target.value)} className={inputClassName} />
              <input value={primaryHorizons} onChange={(e) => setPrimaryHorizons(e.target.value)} className={inputClassName} />
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
          <div className={cardClassName}>
            <label className={labelClassName}>Momentum Exhaustion</label>
            <div className="space-y-2">
              <select
                value={momentumExhaustionMode}
                onChange={(e) =>
                  setMomentumExhaustionMode(e.target.value as MomentumExhaustionMode)
                }
                className={inputClassName}
              >
                <option value="enforce">enforce</option>
                <option value="shadow">shadow</option>
                <option value="off">off</option>
              </select>
              <input
                value={momentumExhaustionMaxScore}
                onChange={(e) => setMomentumExhaustionMaxScore(e.target.value)}
                placeholder="max rank_score"
                className={inputClassName}
              />
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
                    <div>win_rate: {formatRate(oneDay?.win_rate)}</div>
                    <div>avg_return: {formatPercent(oneDay?.avg_return_pct)}</div>
                    <div>median_return: {formatPercent(oneDay?.median_return_pct)}</div>
                  </div>
                </div>
                <div className={cardClassName}>
                  <label className={labelClassName}>3D / 5D</label>
                  <div className="space-y-1 text-sm text-gray-300">
                    <div>3D win_rate: {formatRate(threeDay?.win_rate)}</div>
                    <div>3D avg_return: {formatPercent(threeDay?.avg_return_pct)}</div>
                    <div>5D win_rate: {formatRate(fiveDay?.win_rate)}</div>
                    <div>5D avg_return: {formatPercent(fiveDay?.avg_return_pct)}</div>
                  </div>
                </div>
              </div>

              {primaryValidations.length > 0 ? (
                <div className="space-y-4">
                  {primaryValidations.map((primaryValidation) => (
                    <div key={primaryValidation.primary_horizon_label} className="space-y-4">
                      <div className="text-sm font-semibold text-blue-300">
                        Detailed Validation {primaryValidation.primary_horizon_label}
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
                        <div className={cardClassName}>
                          <label className={labelClassName}>Validation Summary</label>
                          <div className="space-y-1 text-sm text-gray-300">
                            <div>primary: {primaryValidation.primary_horizon_label}</div>
                            <div>count: {String(primaryValidation.overall.count ?? "-")}</div>
                            <div>win_rate: {formatRate(primaryValidation.overall.win_rate)}</div>
                            <div>mean: {formatPercent(primaryValidation.overall.avg_return_pct)}</div>
                            <div>median: {formatPercent(primaryValidation.overall.median_return_pct)}</div>
                            <div>mean &gt; median: {formatBooleanFlag(primaryValidation.overall.mean_gt_median)}</div>
                          </div>
                        </div>
                        <div className={cardClassName}>
                          <label className={labelClassName}>Risk / Quantiles</label>
                          <div className="space-y-1 text-sm text-gray-300">
                            <div>avg_loss: {formatPercent(primaryValidation.overall.avg_loss_pct)}</div>
                            <div>P10: {formatPercent(primaryValidation.overall.p10_return_pct)}</div>
                            <div>P25: {formatPercent(primaryValidation.overall.p25_return_pct)}</div>
                            <div>P50: {formatPercent(primaryValidation.overall.p50_return_pct)}</div>
                            <div>P75: {formatPercent(primaryValidation.overall.p75_return_pct)}</div>
                            <div>P90: {formatPercent(primaryValidation.overall.p90_return_pct)}</div>
                          </div>
                        </div>
                        <div className={cardClassName}>
                          <label className={labelClassName}>Tail Robustness</label>
                          <div className="space-y-1 text-sm text-gray-300">
                            <div>trimmed_1: {formatPercent(primaryValidation.overall.trimmed_mean_1pct_return_pct)}</div>
                            <div>trimmed_5: {formatPercent(primaryValidation.overall.trimmed_mean_5pct_return_pct)}</div>
                            <div>winsorized_1: {formatPercent(primaryValidation.overall.winsorized_mean_1pct_return_pct)}</div>
                            <div>winsorized_5: {formatPercent(primaryValidation.overall.winsorized_mean_5pct_return_pct)}</div>
                            <div>top_1_contrib: {formatRate(primaryValidation.overall.top_1pct_contribution_ratio)}</div>
                            <div>top_5_contrib: {formatRate(primaryValidation.overall.top_5pct_contribution_ratio)}</div>
                            <div>net_wo_top_5: {formatPercent(primaryValidation.overall.net_without_top_5pct_return_pct)}</div>
                            <div>max: {formatPercent(primaryValidation.overall.max_return_pct)}</div>
                            <div>min: {formatPercent(primaryValidation.overall.min_return_pct)}</div>
                          </div>
                        </div>
                        <div className={cardClassName}>
                          <label className={labelClassName}>Regime / Strength Meta</label>
                          <div className="space-y-1 text-sm text-gray-300">
                            <div>strength_metric: {primaryValidation.signal_strength_metric ?? "-"}</div>
                            <div>strength_buckets: {primaryValidation.signal_strength_bucket_method ?? "-"}</div>
                            <div>regime_source: {primaryValidation.market_regime_source ?? "-"}</div>
                            <div>regime_status: {primaryValidation.market_regime_status ?? "-"}</div>
                            <div className="text-xs text-gray-500">{primaryValidation.market_regime_definition ?? "No market regime definition."}</div>
                          </div>
                        </div>
                      </div>

                      <div className="grid grid-cols-1 gap-4">
                        <ValidationTable title="By Year" slices={primaryValidation.by_year ?? []} />
                        <ValidationTable title="By Strategy" slices={primaryValidation.by_strategy ?? []} />
                        <ValidationTable title="By Strategy Bucket" slices={primaryValidation.by_strategy_bucket ?? []} />
                        <ValidationTable title="By Entry Filter" slices={primaryValidation.by_entry_filter ?? []} />
                        <ValidationTable title="By Market Regime" slices={primaryValidation.by_market_regime ?? []} />
                        <ValidationTable title="By Signal Strength Bucket" slices={primaryValidation.by_signal_strength_bucket ?? []} />
                        <ValidationTable title="By Month" slices={primaryValidation.by_month ?? []} />
                        <TailRobustnessRankingTable
                          title={`${primaryValidation.primary_horizon_label} Tail Robustness Ranking`}
                          rankings={primaryValidation.by_strategy_tail_robustness ?? []}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className={cardClassName}>
                  <label className={labelClassName}>Detailed Horizon Validation</label>
                  <div className="text-sm text-gray-500">This dataset does not include detailed horizon validation yet.</div>
                </div>
              )}

              {topDailyWindowsByHorizon.length > 0 ? (
                <div className="grid grid-cols-1 gap-4">
                  {topDailyWindowsByHorizon.map((groupedWindows) => (
                    <div key={groupedWindows.primary_horizon_label} className={cardClassName}>
                      <label className={labelClassName}>
                        Top Daily Windows ({groupedWindows.primary_horizon_label})
                      </label>
                      <div className="mb-2 text-xs text-gray-500">
                        sorted by {groupedWindows.sort_column}
                      </div>
                      <pre className="overflow-x-auto whitespace-pre-wrap text-xs text-gray-300">
                        {JSON.stringify(groupedWindows.windows ?? [], null, 2)}
                      </pre>
                    </div>
                  ))}
                </div>
              ) : (
                <div className={cardClassName}>
                  <label className={labelClassName}>Top Daily Windows</label>
                  <div className="text-sm text-gray-500">This dataset does not include top daily window rankings yet.</div>
                </div>
              )}
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

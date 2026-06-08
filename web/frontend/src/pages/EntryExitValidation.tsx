import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  api,
  type EntryExitValidationDatasetDetail,
  type EntryExitValidationDatasetSummary,
  type EntryExitValidationOptions,
  type EntryExitValidationRunRequest,
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

function formatPercent(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return `${value.toFixed(3)}%`;
}

function formatRate(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return `${(value * 100).toFixed(2)}%`;
}

function ComboTable({ title, rows }: { title: string; rows: Array<Record<string, unknown>> }) {
  return (
    <div className={cardClassName}>
      <label className={labelClassName}>{title}</label>
      {rows.length === 0 ? (
        <div className="text-sm text-gray-500">No rows.</div>
      ) : (
        <div className="max-h-[360px] overflow-auto rounded border border-gray-800">
          <table className="min-w-full text-left text-xs text-gray-300">
            <thead className="sticky top-0 bg-gray-950/95 text-gray-400">
              <tr>
                <th className="px-3 py-2">Entry</th>
                <th className="px-3 py-2">Exit</th>
                <th className="px-3 py-2 text-right">Count</th>
                <th className="px-3 py-2 text-right">Win</th>
                <th className="px-3 py-2 text-right">Avg</th>
                <th className="px-3 py-2 text-right">Median</th>
                <th className="px-3 py-2 text-right">Trim5</th>
                <th className="px-3 py-2 text-right">P10</th>
                <th className="px-3 py-2 text-right">ES5</th>
                <th className="px-3 py-2 text-right">Top5</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={`${row.entry_strategy}-${row.exit_strategy}-${index}`} className="border-t border-gray-800 align-top">
                  <td className="px-3 py-2 font-medium text-gray-200">{String(row.entry_strategy ?? "-")}</td>
                  <td className="px-3 py-2">{String(row.exit_strategy ?? "-")}</td>
                  <td className="px-3 py-2 text-right">{String(row.count ?? "-")}</td>
                  <td className="px-3 py-2 text-right">{formatRate(row.win_rate)}</td>
                  <td className="px-3 py-2 text-right">{formatPercent(row.avg_return)}</td>
                  <td className="px-3 py-2 text-right">{formatPercent(row.median_return)}</td>
                  <td className="px-3 py-2 text-right">{formatPercent(row.trimmed_mean_5pct)}</td>
                  <td className="px-3 py-2 text-right">{formatPercent(row.p10_return)}</td>
                  <td className="px-3 py-2 text-right">{formatPercent(row.expected_shortfall_5pct)}</td>
                  <td className="px-3 py-2 text-right">{formatRate(row.top_5pct_contribution_ratio)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function EntryExitValidation() {
  const exec = useStreamExec();
  const options = useQuery<EntryExitValidationOptions>({
    queryKey: ["entry-exit-validation-options"],
    queryFn: api.entryExitValidationOptions,
  });

  const [initialized, setInitialized] = useState(false);
  const [selectedEntry, setSelectedEntry] = useState<string[]>([]);
  const [selectedExit, setSelectedExit] = useState<string[]>([]);
  const [universeFiles, setUniverseFiles] = useState("");
  const [years, setYears] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [horizons, setHorizons] = useState("3,5,7,9,11");
  const [primaryHorizon, setPrimaryHorizon] = useState("5");
  const [executionMode, setExecutionMode] = useState<"next_open" | "signal_close">("next_open");
  const [signalScope, setSignalScope] = useState<"all" | "selected">("all");
  const [rankingStrategy, setRankingStrategy] = useState("momentum");
  const [entryFilterMode, setEntryFilterMode] = useState<"auto" | "off" | "atr" | "single" | "grid">("auto");
  const [entryFilterNames, setEntryFilterNames] = useState("");
  const [atrRatioMin, setAtrRatioMin] = useState("");
  const [atrRatioMax, setAtrRatioMax] = useState("");
  const [tailGuardEnabled, setTailGuardEnabled] = useState(true);
  const [tailGuardMaxRank, setTailGuardMaxRank] = useState("12");
  const [momentumExhaustionMode, setMomentumExhaustionMode] =
    useState<MomentumExhaustionMode>("enforce");
  const [momentumExhaustionMaxScore, setMomentumExhaustionMaxScore] =
    useState("4.0");
  const [maxHoldingTradingDays, setMaxHoldingTradingDays] = useState("60");
  const [minSamples, setMinSamples] = useState("30");
  const [limit, setLimit] = useState("");
  const [dataRoot, setDataRoot] = useState("data");
  const [outputDir, setOutputDir] = useState("");
  const [selectedDataset, setSelectedDataset] = useState("");

  const datasets = useQuery<EntryExitValidationDatasetSummary[]>({
    queryKey: ["entry-exit-validation-datasets", outputDir],
    queryFn: () => api.entryExitValidationDatasets(outputDir.trim() || undefined),
  });
  const datasetSummary = useQuery<EntryExitValidationDatasetDetail>({
    queryKey: ["entry-exit-validation-summary", selectedDataset, outputDir],
    queryFn: () =>
      api.entryExitValidationDatasetSummary(
        selectedDataset,
        outputDir.trim() || undefined,
      ),
    enabled: Boolean(selectedDataset),
  });

  useEffect(() => {
    if (!options.data || initialized) return;
    const defaults = options.data.defaults;
    setSelectedEntry(defaults.entry_strategies ?? []);
    setSelectedExit(defaults.exit_strategies ?? []);
    setUniverseFiles((defaults.universe_files ?? []).join("\n"));
    setHorizons((defaults.horizons ?? [3, 5, 7, 9, 11]).join(","));
    setPrimaryHorizon(String(defaults.primary_horizon ?? 5));
    setExecutionMode((defaults.execution_mode as "next_open" | "signal_close") ?? "next_open");
    setSignalScope((defaults.signal_scope as "all" | "selected") ?? "all");
    setRankingStrategy(defaults.ranking_strategy ?? "momentum");
    setEntryFilterMode((defaults.entry_filter_mode as "auto" | "off" | "atr" | "single" | "grid") ?? "auto");
    setEntryFilterNames((defaults.entry_filter_names ?? []).join(","));
    setAtrRatioMin(defaults.atr_ratio_min == null ? "" : String(defaults.atr_ratio_min));
    setAtrRatioMax(defaults.atr_ratio_max == null ? "" : String(defaults.atr_ratio_max));
    setTailGuardEnabled(Boolean(defaults.tail_guard_enabled));
    setTailGuardMaxRank(String(defaults.tail_guard_max_rank ?? 12));
    setMomentumExhaustionMode(defaults.momentum_exhaustion_mode ?? "enforce");
    setMomentumExhaustionMaxScore(
      String(defaults.momentum_exhaustion_max_score ?? 4.0),
    );
    setMaxHoldingTradingDays(String(defaults.max_holding_trading_days ?? 60));
    setMinSamples(String(defaults.min_samples ?? 30));
    setDataRoot(defaults.data_root ?? "data");
    setOutputDir(defaults.output_dir ?? "entry_exit_validation");
    setInitialized(true);
  }, [initialized, options.data]);

  useEffect(() => {
    if (exec.exitCode === 0) void datasets.refetch();
  }, [datasets, exec.exitCode]);

  useEffect(() => {
    if (!selectedDataset && datasets.data && datasets.data.length > 0) {
      setSelectedDataset(datasets.data[0]?.id ?? "");
    }
  }, [datasets.data, selectedDataset]);

  const summary = datasetSummary.data?.summary;
  const robustRows = useMemo(() => summary?.top_robust_combinations ?? [], [summary]);
  const riskRows = useMemo(() => summary?.top_risk_combinations ?? [], [summary]);
  const artifacts = summary?.artifacts ?? {};

  function handleRun() {
    const parsedYears = parseIntegerList(years);
    const body: EntryExitValidationRunRequest = {
      entry_strategies: selectedEntry,
      exit_strategies: selectedExit,
      universe_files: parseStringList(universeFiles),
      years: parsedYears.length > 0 ? parsedYears : undefined,
      start: parsedYears.length > 0 ? undefined : start.trim() || undefined,
      end: parsedYears.length > 0 ? undefined : end.trim() || undefined,
      horizons: parseIntegerList(horizons),
      primary_horizon: Number.parseInt(primaryHorizon, 10) || 5,
      execution_mode: executionMode,
      signal_scope: signalScope,
      ranking_strategy: rankingStrategy.trim() || undefined,
      entry_filter_mode: entryFilterMode,
      entry_filter_names: parseStringList(entryFilterNames),
      atr_ratio_min: parseOptionalNumber(atrRatioMin),
      atr_ratio_max: parseOptionalNumber(atrRatioMax),
      tail_guard_enabled: tailGuardEnabled,
      tail_guard_max_rank: parseOptionalNumber(tailGuardMaxRank),
      momentum_exhaustion_mode: momentumExhaustionMode,
      momentum_exhaustion_max_score: parseOptionalNumber(momentumExhaustionMaxScore),
      momentum_exhaustion_threshold_method: "absolute",
      max_holding_trading_days: Number.parseInt(maxHoldingTradingDays, 10) || 60,
      partial_exit_policy: "first_sell_full_exit",
      min_samples: Number.parseInt(minSamples, 10) || 30,
      limit: parseOptionalNumber(limit),
      data_root: dataRoot.trim() || "data",
      output_dir: outputDir.trim() || undefined,
    };
    void exec.execute("/api/entry-exit-validation/run", body);
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-gray-100">Entry x Exit Validation</h2>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-2">
            <StrategyMultiSelect
              label="Entry Strategies"
              options={options.data?.entry_strategies ?? []}
              selected={selectedEntry}
              onChange={setSelectedEntry}
            />
            <StrategyMultiSelect
              label="Exit Strategies"
              options={options.data?.exit_strategies ?? []}
              selected={selectedExit}
              onChange={setSelectedExit}
            />
          </div>

          <div className={cardClassName}>
            <div className="grid gap-4 md:grid-cols-3">
              <div>
                <label className={labelClassName}>Years</label>
                <input className={inputClassName} value={years} onChange={(event) => setYears(event.target.value)} placeholder="2024,2025,2026" />
              </div>
              <div>
                <label className={labelClassName}>Start</label>
                <input className={inputClassName} value={start} onChange={(event) => setStart(event.target.value)} placeholder="YYYY-MM-DD" />
              </div>
              <div>
                <label className={labelClassName}>End</label>
                <input className={inputClassName} value={end} onChange={(event) => setEnd(event.target.value)} placeholder="YYYY-MM-DD" />
              </div>
              <div className="md:col-span-3">
                <label className={labelClassName}>Universe Files</label>
                <textarea className="min-h-[70px] w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm" value={universeFiles} onChange={(event) => setUniverseFiles(event.target.value)} />
              </div>
              <div>
                <label className={labelClassName}>Horizons</label>
                <input className={inputClassName} value={horizons} onChange={(event) => setHorizons(event.target.value)} />
              </div>
              <div>
                <label className={labelClassName}>Primary Horizon</label>
                <input className={inputClassName} value={primaryHorizon} onChange={(event) => setPrimaryHorizon(event.target.value)} />
              </div>
              <div>
                <label className={labelClassName}>Max Holding Trading Days</label>
                <input className={inputClassName} value={maxHoldingTradingDays} onChange={(event) => setMaxHoldingTradingDays(event.target.value)} />
              </div>
              <div>
                <label className={labelClassName}>Execution</label>
                <select className={inputClassName} value={executionMode} onChange={(event) => setExecutionMode(event.target.value as "next_open" | "signal_close")}>
                  <option value="next_open">next_open</option>
                  <option value="signal_close">signal_close</option>
                </select>
              </div>
              <div>
                <label className={labelClassName}>Signal Scope</label>
                <select className={inputClassName} value={signalScope} onChange={(event) => setSignalScope(event.target.value as "all" | "selected")}>
                  <option value="all">all</option>
                  <option value="selected">selected</option>
                </select>
              </div>
              <div>
                <label className={labelClassName}>Ranking Strategy</label>
                <input className={inputClassName} value={rankingStrategy} onChange={(event) => setRankingStrategy(event.target.value)} />
              </div>
              <div>
                <label className={labelClassName}>Entry Filter Mode</label>
                <select className={inputClassName} value={entryFilterMode} onChange={(event) => setEntryFilterMode(event.target.value as "auto" | "off" | "atr" | "single" | "grid")}>
                  <option value="auto">auto</option>
                  <option value="off">off</option>
                  <option value="atr">atr</option>
                  <option value="single">single</option>
                  <option value="grid">grid</option>
                </select>
              </div>
              <div>
                <label className={labelClassName}>Entry Filter Names</label>
                <input className={inputClassName} value={entryFilterNames} onChange={(event) => setEntryFilterNames(event.target.value)} />
              </div>
              <div>
                <label className={labelClassName}>ATR Ratio Min</label>
                <input className={inputClassName} value={atrRatioMin} onChange={(event) => setAtrRatioMin(event.target.value)} />
              </div>
              <div>
                <label className={labelClassName}>ATR Ratio Max</label>
                <input className={inputClassName} value={atrRatioMax} onChange={(event) => setAtrRatioMax(event.target.value)} />
              </div>
              <div>
                <label className={labelClassName}>Tail Guard Max Rank</label>
                <input className={inputClassName} value={tailGuardMaxRank} onChange={(event) => setTailGuardMaxRank(event.target.value)} />
              </div>
              <div>
                <label className={labelClassName}>Momentum Exhaustion</label>
                <select className={inputClassName} value={momentumExhaustionMode} onChange={(event) => setMomentumExhaustionMode(event.target.value as MomentumExhaustionMode)}>
                  <option value="enforce">enforce</option>
                  <option value="shadow">shadow</option>
                  <option value="off">off</option>
                </select>
              </div>
              <div>
                <label className={labelClassName}>Momentum Max Score</label>
                <input className={inputClassName} value={momentumExhaustionMaxScore} onChange={(event) => setMomentumExhaustionMaxScore(event.target.value)} />
              </div>
              <label className="flex items-center gap-2 text-sm text-gray-300">
                <input type="checkbox" checked={tailGuardEnabled} onChange={(event) => setTailGuardEnabled(event.target.checked)} />
                Tail guard enabled
              </label>
              <div>
                <label className={labelClassName}>Min Samples</label>
                <input className={inputClassName} value={minSamples} onChange={(event) => setMinSamples(event.target.value)} />
              </div>
              <div>
                <label className={labelClassName}>Limit</label>
                <input className={inputClassName} value={limit} onChange={(event) => setLimit(event.target.value)} />
              </div>
              <div>
                <label className={labelClassName}>Data Root</label>
                <input className={inputClassName} value={dataRoot} onChange={(event) => setDataRoot(event.target.value)} />
              </div>
              <div className="md:col-span-2">
                <label className={labelClassName}>Output Dir</label>
                <input className={inputClassName} value={outputDir} onChange={(event) => setOutputDir(event.target.value)} />
              </div>
            </div>
            <button
              type="button"
              onClick={handleRun}
              disabled={exec.running}
              className="mt-4 rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {exec.running ? "Running..." : "Run Validation"}
            </button>
          </div>
        </div>

        <div className="space-y-4">
          <div className={cardClassName}>
            <label className={labelClassName}>Datasets</label>
            <select className={inputClassName} value={selectedDataset} onChange={(event) => setSelectedDataset(event.target.value)}>
              <option value="">Select dataset</option>
              {(datasets.data ?? []).map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {dataset.id} ({dataset.simulated_trade_count})
                </option>
              ))}
            </select>
          </div>
          <LogOutput lines={exec.lines} running={exec.running} exitCode={exec.exitCode} />
        </div>
      </div>

      {summary ? (
        <div className="space-y-4">
          <div className="grid gap-4 md:grid-cols-4">
            <div className={cardClassName}><div className="text-xs text-gray-500">Candidates</div><div className="mt-1 text-xl text-gray-100">{summary.candidate_count ?? 0}</div></div>
            <div className={cardClassName}><div className="text-xs text-gray-500">Trades</div><div className="mt-1 text-xl text-gray-100">{summary.simulated_trade_count ?? 0}</div></div>
            <div className={cardClassName}><div className="text-xs text-gray-500">Combinations</div><div className="mt-1 text-xl text-gray-100">{summary.combination_count ?? 0}</div></div>
            <div className={cardClassName}><div className="text-xs text-gray-500">Regime</div><div className="mt-1 text-sm text-gray-100">{summary.market_regime_status ?? "-"}</div></div>
          </div>
          <ComboTable title="Robustness Ranking" rows={robustRows} />
          <ComboTable title="Risk Ranking" rows={riskRows} />
          <div className={cardClassName}>
            <label className={labelClassName}>Warnings</label>
            {(summary.warnings ?? []).length === 0 ? <div className="text-sm text-gray-500">No warnings.</div> : (
              <ul className="space-y-1 text-sm text-amber-300">
                {(summary.warnings ?? []).map((warning) => <li key={warning}>{warning}</li>)}
              </ul>
            )}
          </div>
          <div className={cardClassName}>
            <label className={labelClassName}>Artifacts</label>
            <div className="grid gap-2 text-xs text-gray-400 md:grid-cols-2">
              {Object.entries(artifacts).map(([key, value]) => (
                <div key={key} className="truncate"><span className="text-gray-500">{key}: </span>{String(value)}</div>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

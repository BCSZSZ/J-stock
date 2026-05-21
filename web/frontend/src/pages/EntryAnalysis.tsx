import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  api,
  type EntryAnalysisAggregateResponse,
  type EntryAnalysisFeatureCondition,
  type EntryAnalysisOptions,
} from "../api/client";
import StrategyMultiSelect from "../components/StrategyMultiSelect";
import LogOutput from "../components/LogOutput";
import { useStreamExec } from "../hooks/useStreamExec";

type ConditionDraft = EntryAnalysisFeatureCondition & {
  id: string;
};

const fieldCardClassName =
  "rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-3 h-full flex flex-col";
const compactInputClassName =
  "h-10 w-full rounded border border-gray-700 bg-gray-800 px-3 text-sm";
const compactLabelClassName =
  "text-xs uppercase tracking-wide text-gray-500 block mb-2";

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

function parseOptionalNumber(value: unknown): number | undefined {
  if (value === null || value === undefined) return undefined;
  const text = String(value).trim();
  if (!text) return undefined;
  const parsed = Number(text);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function formatNumber(value: unknown, digits = 2): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "-";
  return parsed.toFixed(digits);
}

function formatPercent(value: unknown): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "-";
  return `${(parsed * 100).toFixed(2)}%`;
}

function newCondition(feature = "RSI"): ConditionDraft {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    feature,
    operator: "between",
    min: 40,
    max: 70,
    value: null,
  };
}

function statFor(result: EntryAnalysisAggregateResponse | null, key: string) {
  const value = result?.filtered?.[key];
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : null;
}

function baselineFor(result: EntryAnalysisAggregateResponse | null, key: string) {
  const value = result?.baseline?.[key];
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : null;
}

export default function EntryAnalysis() {
  const options = useQuery<EntryAnalysisOptions>({
    queryKey: ["entry-analysis-options"],
    queryFn: api.entryAnalysisOptions,
  });
  const exec = useStreamExec();
  const [selectedEntry, setSelectedEntry] = useState<string[]>([]);
  const [strategyOpen, setStrategyOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [universeFiles, setUniverseFiles] = useState("");
  const [years, setYears] = useState(String(new Date().getFullYear()));
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [limit, setLimit] = useState("");
  const [horizons, setHorizons] = useState("3,5,10");
  const [primaryHorizon, setPrimaryHorizon] = useState("5");
  const [labelMode, setLabelMode] = useState("signal_close");
  const [outputDir, setOutputDir] = useState("");
  const [dataRoot, setDataRoot] = useState("data");
  const [initialized, setInitialized] = useState(false);

  const [selectedDataset, setSelectedDataset] = useState("");
  const [conditions, setConditions] = useState<ConditionDraft[]>([newCondition()]);
  const [logic, setLogic] = useState<"all" | "any">("all");
  const [analysisHorizons, setAnalysisHorizons] = useState("3,5,10");
  const [groupBy, setGroupBy] = useState("");
  const [minSamples, setMinSamples] = useState("30");
  const [aggregateResult, setAggregateResult] = useState<EntryAnalysisAggregateResponse | null>(null);
  const [aggregateError, setAggregateError] = useState<string | null>(null);
  const [aggregateLoading, setAggregateLoading] = useState(false);

  const datasets = useQuery({
    queryKey: ["entry-analysis-datasets", outputDir],
    queryFn: () => api.entryAnalysisDatasets(outputDir.trim() || undefined),
  });
  const schema = useQuery({
    queryKey: ["entry-analysis-dataset-schema", selectedDataset, outputDir],
    queryFn: () => api.entryAnalysisDatasetSchema(selectedDataset, outputDir.trim() || undefined),
    enabled: Boolean(selectedDataset),
  });

  useEffect(() => {
    if (!options.data || initialized) return;
    const defaults = options.data.defaults;
    setSelectedEntry(defaults.entry_strategies ?? []);
    setUniverseFiles((defaults.universe_files ?? []).join("\n"));
    setHorizons((defaults.horizons ?? [3, 5, 10]).join(","));
    setAnalysisHorizons((defaults.horizons ?? [3, 5, 10]).join(","));
    setPrimaryHorizon(String(defaults.primary_horizon ?? 5));
    setLabelMode(defaults.label_mode ?? "signal_close");
    setDataRoot(defaults.data_root ?? "data");
    setOutputDir(defaults.output_dir ?? "entry_analysis");
    setInitialized(true);
  }, [initialized, options.data]);

  useEffect(() => {
    if (exec.exitCode === 0) {
      void datasets.refetch();
    }
  }, [exec.exitCode]);

  useEffect(() => {
    if (!selectedDataset && datasets.data && datasets.data.length > 0) {
      setSelectedDataset(datasets.data[0]?.id ?? "");
    }
  }, [datasets.data, selectedDataset]);

  const featureOptions = useMemo(() => {
    const fromSchema = schema.data?.feature_columns ?? [];
    if (fromSchema.length > 0) return fromSchema;
    const merged = [
      ...(options.data?.indicator_columns ?? []),
      ...(options.data?.derived_feature_columns ?? []),
    ];
    return Array.from(new Set(merged));
  }, [options.data, schema.data]);

  const strategySummary = selectedEntry.length === 0
    ? "No strategy selected"
    : selectedEntry.length <= 3
      ? selectedEntry.join(", ")
      : `${selectedEntry.slice(0, 3).join(", ")} +${selectedEntry.length - 3}`;

  function updateCondition(id: string, patch: Partial<ConditionDraft>) {
    setConditions((current) =>
      current.map((condition) => (condition.id === id ? { ...condition, ...patch } : condition)),
    );
  }

  function handleGenerateDataset() {
    const parsedHorizons = parseIntegerList(horizons);
    const parsedYears = parseIntegerList(years);
    const parsedPrimary = parseOptionalNumber(primaryHorizon) ?? parsedHorizons[0] ?? 5;
    const parsedLimit = parseOptionalNumber(limit);

    const body = {
      entry_strategies: selectedEntry,
      universe_files: parseStringList(universeFiles),
      years: parsedYears.length > 0 ? parsedYears : undefined,
      start: parsedYears.length === 0 ? start.trim() || undefined : undefined,
      end: parsedYears.length === 0 ? end.trim() || undefined : undefined,
      horizons: parsedHorizons.length > 0 ? parsedHorizons : [3, 5, 10],
      primary_horizon: parsedPrimary,
      rules: [],
      preset_rules: "none",
      label_mode: labelMode,
      min_samples: 1,
      include_joint: false,
      save_candidates: true,
      limit: parsedLimit ?? null,
      data_root: dataRoot.trim() || "data",
      output_dir: outputDir.trim() || undefined,
    };

    void exec.execute("/entry-analysis/run", body);
  }

  async function handleAggregate() {
    if (!selectedDataset) return;
    setAggregateLoading(true);
    setAggregateError(null);
    try {
      const body = {
        conditions: conditions
          .filter((condition) => condition.feature)
          .map(({ id: _id, ...condition }) => condition),
        logic,
        horizons: parseIntegerList(analysisHorizons),
        group_by: groupBy || null,
        min_samples: parseOptionalNumber(minSamples) ?? 1,
      };
      const result = await api.entryAnalysisAggregate(
        selectedDataset,
        body,
        outputDir.trim() || undefined,
      );
      setAggregateResult(result);
    } catch (error) {
      setAggregateError(error instanceof Error ? error.message : String(error));
    } finally {
      setAggregateLoading(false);
    }
  }

  const activeHorizons = parseIntegerList(analysisHorizons);
  const primaryKey = `${parseOptionalNumber(primaryHorizon) ?? activeHorizons[0] ?? 5}d`;
  const primaryStats = statFor(aggregateResult, primaryKey);
  const primaryBaseline = baselineFor(aggregateResult, primaryKey);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <h2 className="text-2xl font-bold">Entry Analysis</h2>
          <p className="text-sm text-gray-500">
            Generate BUY-signal datasets first, then analyze saved datasets with feature filters.
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
          Failed to load entry-analysis options: {String(options.error)}
        </div>
      )}

      <section className="rounded-lg border border-gray-800 bg-gray-950/40 p-4">
        <div className="mb-4 flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div>
            <h3 className="text-lg font-semibold">Generate Buy Signal Dataset</h3>
            <p className="text-xs text-gray-500">
              Output root: <span className="font-mono text-gray-300">{outputDir || "entry_analysis"}</span>
            </p>
          </div>
          <button
            type="button"
            onClick={handleGenerateDataset}
            disabled={exec.running || selectedEntry.length === 0}
            className="h-10 rounded bg-blue-600 px-4 text-sm hover:bg-blue-500 disabled:opacity-50"
          >
            Generate Dataset
          </button>
        </div>

        <div className="grid gap-3 xl:grid-cols-6">
          <div className={`${fieldCardClassName} xl:col-span-3`}>
            <label className={compactLabelClassName}>Entry Strategies</label>
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div className="min-w-0">
                <div className="text-sm text-gray-200">{selectedEntry.length} selected</div>
                <div className="mt-1 truncate text-xs text-gray-500">{strategySummary}</div>
              </div>
              <button
                type="button"
                onClick={() => setStrategyOpen((current) => !current)}
                className="h-9 rounded border border-gray-700 px-3 text-sm hover:bg-gray-800"
              >
                {strategyOpen ? "Hide Selector" : "Choose Strategies"}
              </button>
            </div>
            {selectedEntry.length > 0 && (
              <div className="mt-3 flex max-h-20 flex-wrap gap-2 overflow-y-auto pr-1">
                {selectedEntry.map((item) => (
                  <button
                    key={item}
                    type="button"
                    onClick={() => setSelectedEntry((current) => current.filter((value) => value !== item))}
                    className="rounded-full border border-blue-700 bg-blue-950/60 px-2.5 py-1 text-xs text-blue-100"
                  >
                    {item}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className={`${fieldCardClassName} xl:col-span-3`}>
            <label className={compactLabelClassName}>Universe Files</label>
            <div className="rounded border border-gray-800 bg-gray-900/60 px-3 py-2 font-mono text-xs text-gray-300">
              {parseStringList(universeFiles).map((item) => (
                <div key={item} className="truncate">{item}</div>
              ))}
            </div>
            <div className="mt-3 grid gap-2 md:grid-cols-4">
              <div>
                <label className={compactLabelClassName}>Years</label>
                <input value={years} onChange={(event) => setYears(event.target.value)} className={compactInputClassName} />
              </div>
              <div>
                <label className={compactLabelClassName}>Start</label>
                <input value={start} onChange={(event) => setStart(event.target.value)} placeholder="YYYY-MM-DD" className={compactInputClassName} />
              </div>
              <div>
                <label className={compactLabelClassName}>End</label>
                <input value={end} onChange={(event) => setEnd(event.target.value)} placeholder="YYYY-MM-DD" className={compactInputClassName} />
              </div>
              <div>
                <label className={compactLabelClassName}>Limit</label>
                <input value={limit} onChange={(event) => setLimit(event.target.value)} placeholder="optional" className={compactInputClassName} />
              </div>
            </div>
          </div>
        </div>

        {strategyOpen && (
          <div className="mt-3">
            <StrategyMultiSelect
              label="Entry Strategies"
              options={options.data?.entry_strategies ?? []}
              selected={selectedEntry}
              onChange={setSelectedEntry}
              searchPlaceholder="Search entry strategies..."
            />
          </div>
        )}

        <div className="mt-3 rounded-lg border border-gray-800 bg-gray-950/30">
          <button
            type="button"
            onClick={() => setAdvancedOpen((current) => !current)}
            className="flex w-full items-center justify-between px-3 py-2 text-left text-sm text-gray-200 hover:bg-gray-900/60"
          >
            <span>Advanced Dataset Settings</span>
            <span className="text-gray-500">{advancedOpen ? "Hide" : "Show"}</span>
          </button>
          {advancedOpen && (
            <div className="grid gap-3 border-t border-gray-800 p-3 md:grid-cols-2 xl:grid-cols-5">
              <div>
                <label className={compactLabelClassName}>Horizons</label>
                <input value={horizons} onChange={(event) => setHorizons(event.target.value)} className={compactInputClassName} />
                <p className="mt-1 text-xs text-gray-500">Trading-day returns saved for every BUY signal.</p>
              </div>
              <div>
                <label className={compactLabelClassName}>Primary</label>
                <input value={primaryHorizon} onChange={(event) => setPrimaryHorizon(event.target.value)} className={compactInputClassName} />
                <p className="mt-1 text-xs text-gray-500">Default horizon for ranking analysis tables.</p>
              </div>
              <div>
                <label className={compactLabelClassName}>Label Mode</label>
                <select value={labelMode} onChange={(event) => setLabelMode(event.target.value)} className={compactInputClassName}>
                  {(options.data?.label_modes ?? ["signal_close", "next_open"]).map((mode) => (
                    <option key={mode} value={mode}>{mode}</option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-gray-500">signal_close starts returns from the signal-day close.</p>
              </div>
              <div>
                <label className={compactLabelClassName}>Data Root</label>
                <input value={dataRoot} onChange={(event) => setDataRoot(event.target.value)} className={compactInputClassName} />
                <p className="mt-1 text-xs text-gray-500">Source folder for cached market features.</p>
              </div>
              <div>
                <label className={compactLabelClassName}>Output Dir</label>
                <input value={outputDir} onChange={(event) => setOutputDir(event.target.value)} className={compactInputClassName} />
                <p className="mt-1 text-xs text-gray-500">Defaults to the G-drive Entry Analysis folder when available.</p>
              </div>
            </div>
          )}
        </div>

        <div className="mt-3">
          <LogOutput lines={exec.lines} running={exec.running} exitCode={exec.exitCode} />
        </div>
      </section>

      <section className="grid gap-3 xl:grid-cols-6">
        <div className={`${fieldCardClassName} xl:col-span-2`}>
          <h3 className="mb-3 text-lg font-semibold">Datasets</h3>
          <div className="max-h-[34rem] space-y-2 overflow-y-auto pr-1">
            {(datasets.data ?? []).map((dataset) => (
              <button
                key={dataset.id}
                type="button"
                onClick={() => {
                  setSelectedDataset(dataset.id);
                  setAggregateResult(null);
                }}
                className={`block w-full rounded border px-3 py-2 text-left text-xs ${
                  selectedDataset === dataset.id
                    ? "border-blue-500 bg-blue-950/30 text-blue-100"
                    : "border-gray-800 bg-gray-900/40 text-gray-300 hover:bg-gray-900"
                }`}
              >
                <div className="break-all font-mono">{dataset.id}</div>
                <div className="mt-1 text-gray-500">
                  {dataset.candidate_count} signals / {dataset.start_date} to {dataset.end_date}
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className={`${fieldCardClassName} xl:col-span-4`}>
          <div className="mb-4 flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <div>
              <h3 className="text-lg font-semibold">Analyze Dataset</h3>
              <p className="text-xs text-gray-500">
                {schema.data
                  ? `${schema.data.candidate_count} saved BUY signals, ${schema.data.feature_columns.length} features`
                  : "Select a dataset to inspect feature intervals."}
              </p>
            </div>
            <button
              type="button"
              onClick={handleAggregate}
              disabled={!selectedDataset || aggregateLoading}
              className="h-10 rounded bg-blue-600 px-4 text-sm hover:bg-blue-500 disabled:opacity-50"
            >
              {aggregateLoading ? "Analyzing..." : "Update Analysis"}
            </button>
          </div>

          <div className="grid gap-3 xl:grid-cols-4">
            <div>
              <label className={compactLabelClassName}>Match</label>
              <select value={logic} onChange={(event) => setLogic(event.target.value as "all" | "any")} className={compactInputClassName}>
                <option value="all">All conditions (AND)</option>
                <option value="any">Any condition (OR)</option>
              </select>
            </div>
            <div>
              <label className={compactLabelClassName}>Horizons</label>
              <input value={analysisHorizons} onChange={(event) => setAnalysisHorizons(event.target.value)} className={compactInputClassName} />
            </div>
            <div>
              <label className={compactLabelClassName}>Min Samples</label>
              <input value={minSamples} onChange={(event) => setMinSamples(event.target.value)} className={compactInputClassName} />
            </div>
            <div>
              <label className={compactLabelClassName}>Group By</label>
              <select value={groupBy} onChange={(event) => setGroupBy(event.target.value)} className={compactInputClassName}>
                <option value="">No grouping</option>
                {featureOptions.map((feature) => (
                  <option key={feature} value={feature}>{feature}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="mt-4 space-y-2">
            {conditions.map((condition, index) => (
              <div key={condition.id} className="grid gap-2 rounded border border-gray-800 bg-gray-900/50 p-2 md:grid-cols-6">
                <div className="md:col-span-2">
                  <label className={compactLabelClassName}>Feature {index + 1}</label>
                  <select value={condition.feature} onChange={(event) => updateCondition(condition.id, { feature: event.target.value })} className={compactInputClassName}>
                    {featureOptions.map((feature) => (
                      <option key={feature} value={feature}>{feature}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className={compactLabelClassName}>Operator</label>
                  <select value={condition.operator} onChange={(event) => updateCondition(condition.id, { operator: event.target.value as ConditionDraft["operator"] })} className={compactInputClassName}>
                    {["between", ">=", ">", "<=", "<", "==", "!=", "is_null", "not_null"].map((operator) => (
                      <option key={operator} value={operator}>{operator}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className={compactLabelClassName}>Min</label>
                  <input value={condition.min ?? ""} onChange={(event) => updateCondition(condition.id, { min: parseOptionalNumber(event.target.value) ?? null })} className={compactInputClassName} />
                </div>
                <div>
                  <label className={compactLabelClassName}>Max</label>
                  <input value={condition.max ?? ""} onChange={(event) => updateCondition(condition.id, { max: parseOptionalNumber(event.target.value) ?? null })} className={compactInputClassName} />
                </div>
                <div className="flex items-end gap-2">
                  <button
                    type="button"
                    onClick={() => setConditions((current) => current.filter((item) => item.id !== condition.id))}
                    disabled={conditions.length === 1}
                    className="h-10 flex-1 rounded border border-gray-700 px-2 text-xs hover:bg-gray-800 disabled:opacity-50"
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
            <button
              type="button"
              onClick={() => setConditions((current) => [...current, newCondition(featureOptions[0] ?? "RSI")])}
              className="h-9 rounded border border-gray-700 px-3 text-sm hover:bg-gray-800"
            >
              Add Condition
            </button>
          </div>

          {aggregateError && (
            <div className="mt-4 rounded border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-200">
              {aggregateError}
            </div>
          )}

          {aggregateResult && (
            <div className="mt-4 space-y-4">
              <div className="grid gap-3 md:grid-cols-4">
                <div className="rounded border border-gray-800 bg-gray-900/40 p-3">
                  <div className="text-xs uppercase tracking-wide text-gray-500">Filtered Signals</div>
                  <div className="mt-2 text-2xl font-semibold">{String(aggregateResult.filtered.candidate_count ?? "-")}</div>
                </div>
                <div className="rounded border border-gray-800 bg-gray-900/40 p-3">
                  <div className="text-xs uppercase tracking-wide text-gray-500">{primaryKey} Win Rate</div>
                  <div className="mt-2 text-2xl font-semibold">{formatPercent(primaryStats?.win_rate)}</div>
                  <div className="text-xs text-gray-500">baseline {formatPercent(primaryBaseline?.win_rate)}</div>
                </div>
                <div className="rounded border border-gray-800 bg-gray-900/40 p-3">
                  <div className="text-xs uppercase tracking-wide text-gray-500">{primaryKey} Avg Return</div>
                  <div className="mt-2 text-2xl font-semibold">{formatNumber(primaryStats?.avg_return_pct)}%</div>
                  <div className="text-xs text-gray-500">baseline {formatNumber(primaryBaseline?.avg_return_pct)}%</div>
                </div>
                <div className="rounded border border-gray-800 bg-gray-900/40 p-3">
                  <div className="text-xs uppercase tracking-wide text-gray-500">Lift</div>
                  <div className="mt-2 text-2xl font-semibold">{formatNumber(primaryStats?.lift, 3)}x</div>
                </div>
              </div>

              <div className="grid gap-3 md:grid-cols-3">
                {activeHorizons.map((horizon) => {
                  const key = `${horizon}d`;
                  const stats = statFor(aggregateResult, key);
                  return (
                    <div key={key} className="rounded border border-gray-800 bg-gray-900/40 p-3">
                      <div className="text-sm font-semibold">{key}</div>
                      <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-gray-300">
                        <div>count {String(stats?.count ?? "-")}</div>
                        <div>win {formatPercent(stats?.win_rate)}</div>
                        <div>avg {formatNumber(stats?.avg_return_pct)}%</div>
                        <div>median {formatNumber(stats?.median_return_pct)}%</div>
                      </div>
                    </div>
                  );
                })}
              </div>

              {aggregateResult.groups.length > 0 && (
                <div className="overflow-auto rounded border border-gray-800">
                  <table className="min-w-full text-xs">
                    <thead className="bg-gray-900 text-gray-400">
                      <tr>
                        {["horizon", "feature", "bucket", "count", "win_rate", "avg_return_pct", "lift"].map((column) => (
                          <th key={column} className="whitespace-nowrap px-3 py-2 text-left font-medium">{column}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {aggregateResult.groups.slice(0, 120).map((row, index) => (
                        <tr key={index} className="border-t border-gray-800 odd:bg-gray-950/30">
                          <td className="whitespace-nowrap px-3 py-2">{String(row.horizon ?? "")}</td>
                          <td className="whitespace-nowrap px-3 py-2">{String(row.feature ?? "")}</td>
                          <td className="whitespace-nowrap px-3 py-2">{String(row.bucket ?? "")}</td>
                          <td className="whitespace-nowrap px-3 py-2">{String(row.count ?? "")}</td>
                          <td className="whitespace-nowrap px-3 py-2">{formatPercent(row.win_rate)}</td>
                          <td className="whitespace-nowrap px-3 py-2">{formatNumber(row.avg_return_pct)}%</td>
                          <td className="whitespace-nowrap px-3 py-2">{formatNumber(row.lift, 3)}x</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
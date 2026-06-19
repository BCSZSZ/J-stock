import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  api,
  type IndustryFilterMode,
  type MomentumExhaustionMode,
  type StockPoolOption,
} from "../api/client";
import StrategyMultiSelect from "../components/StrategyMultiSelect";
import ExitStrategyFamilyBuilder from "../components/ExitStrategyFamilyBuilder";
import MultiDatePicker from "../components/MultiDatePicker";
import { useConfirmDialog } from "../components/ConfirmDialog";
import LogOutput from "../components/LogOutput";
import { useStreamExec } from "../hooks/useStreamExec";

type EvaluationCommand =
  | "evaluate"
  | "pos-evaluation"
  | "walk-forward-evaluate"
  | "replay-evaluation";
type EvaluationMode = "annual" | "quarterly" | "monthly" | "custom";
type EntryFilterMode = "atr" | "off" | "single" | "grid" | "auto";
type BuyFillMode = "next_open" | "next_close";
type EntryReferenceMode = "raw_fill" | "buffered_fill";
type CapacityRegimeMode = "off" | "enforce";
type PositionSizingMode = "fixed" | "atr";

interface EvaluationDefaults {
  command: string;
  mode: string;
  include_continuous: boolean;
  override_strategies: boolean;
  buy_fill_mode: string;
  buy_fill_modes?: string[];
  entry_reference_mode: string;
  entry_reference_modes?: string[];
  fill_buffer_enabled: boolean;
  fill_buffer_pct: number;
  entry_strategies: string[];
  exit_strategies: string[];
  ranking_mode: string;
  ranking_strategies: string[];
  entry_filter_mode: string;
  entry_filter_names: string[];
  enable_overlay: boolean;
  overlay_modes: string[];
  capacity_regime_mode: string;
  exit_confirm_days: number | null;
  output_dir: string;
  universe_files: string[];
  universe_pool_ids: string[];
  position_file: string;
  profile_names: string[];
  report_file: string;
  min_train_years: number;
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
}

interface EvaluationOptionsResponse {
  commands: string[];
  entry_strategies: string[];
  exit_strategies: string[];
  ranking_strategies: string[];
  modes: string[];
  entry_filter_modes: string[];
  entry_filter_names: string[];
  overlay_modes: string[];
  buy_fill_modes: string[];
  entry_reference_modes: string[];
  capacity_regime_modes: string[];
  ranking_modes: string[];
  position_profiles: string[];
  production: {
    entry_strategy: string;
    exit_strategy: string;
    ranking_strategy: string;
    monitor_list_file: string;
    stock_pool_catalog_file: string;
    report_file_pattern: string;
  };
  stock_pools: StockPoolOption[];
  defaults: EvaluationDefaults;
}

interface ReplayReportContext {
  report_file: string;
  entry_strategy: string;
  exit_strategy: string;
}

interface CheckboxListProps {
  options: string[];
  selected: string[];
  onToggle: (value: string) => void;
  emptyText?: string;
}

interface StockPoolChecklistProps {
  options: StockPoolOption[];
  selected: string[];
  onToggle: (value: string) => void;
}

const DEFAULT_YEARS = Array.from({ length: 5 }, (_, index) =>
  String(new Date().getFullYear() - 4 + index),
).join(",");

function CheckboxList({
  options,
  selected,
  onToggle,
  emptyText = "No options available.",
}: CheckboxListProps) {
  if (options.length === 0) {
    return <p className="text-xs text-gray-500">{emptyText}</p>;
  }

  return (
    <div className="max-h-44 min-h-[9rem] overflow-y-auto rounded border border-gray-800 bg-gray-950/40 p-2">
      <div className="grid gap-x-3 gap-y-1 sm:grid-cols-2 xl:grid-cols-3">
        {options.map((option) => (
          <label
            key={option}
            className="flex items-start gap-2 rounded px-1.5 py-1 text-xs text-gray-300 cursor-pointer hover:bg-gray-900/60 hover:text-white"
          >
            <input
              type="checkbox"
              checked={selected.includes(option)}
              onChange={() => onToggle(option)}
              className="mt-0.5 rounded"
            />
            <span className="break-all">{option}</span>
          </label>
        ))}
      </div>
    </div>
  );
}

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

function StockPoolChecklist({
  options,
  selected,
  onToggle,
}: StockPoolChecklistProps) {
  if (options.length === 0) {
    return <p className="text-xs text-gray-500">No stock pools configured in the catalog.</p>;
  }

  return (
    <div className="max-h-64 overflow-y-auto rounded border border-gray-800 bg-gray-950/40 p-2 space-y-2">
      {options.map((pool) => {
        const atrRange = formatStockPoolAtrRange(pool);
        return (
          <label
            key={pool.id}
            className={`block rounded border px-3 py-2 text-sm ${pool.enabled ? "cursor-pointer border-gray-800 bg-gray-950/30 hover:border-gray-700 hover:bg-gray-900/50" : "border-gray-900 bg-gray-950/10 opacity-60 cursor-not-allowed"}`}
          >
            <div className="flex items-start gap-3">
              <input
                type="checkbox"
                checked={selected.includes(pool.id)}
                disabled={!pool.enabled}
                onChange={() => onToggle(pool.id)}
                className="mt-1 rounded"
              />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-gray-100">{pool.label}</span>
                  <span className="text-[11px] uppercase tracking-wide text-gray-500">
                    {pool.id}
                  </span>
                  {atrRange && (
                    <span className="rounded bg-gray-800 px-2 py-0.5 text-[11px] text-gray-300">
                      ATR% {atrRange}
                    </span>
                  )}
                  {!pool.enabled && (
                    <span className="rounded bg-gray-800 px-2 py-0.5 text-[11px] text-amber-300">
                      disabled
                    </span>
                  )}
                </div>
                <div className="mt-1 break-all text-xs text-gray-400">
                  Monitor: {pool.monitor_list_file}
                </div>
                {pool.sector_pool_file && (
                  <div className="mt-1 break-all text-xs text-gray-500">
                    Sector Pool: {pool.sector_pool_file}
                  </div>
                )}
                {pool.notes && (
                  <div className="mt-2 text-xs text-gray-500">{pool.notes}</div>
                )}
              </div>
            </div>
          </label>
        );
      })}
    </div>
  );
}

function parseIntegerList(value: string): number[] | undefined {
  const normalized = value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => Number.parseInt(item, 10))
    .filter((item) => Number.isFinite(item));
  return normalized.length > 0 ? normalized : undefined;
}

function parseOptionalInt(value: string): number | undefined {
  const normalized = value.trim();
  if (!normalized) return undefined;
  const parsed = Number.parseInt(normalized, 10);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function parseOptionalFloat(value: string): number | undefined {
  const normalized = value.trim();
  if (!normalized) return undefined;
  const parsed = Number.parseFloat(normalized);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function parseStringList(value: string): string[] {
  const normalized = value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
  return Array.from(new Set(normalized));
}

function formatReplayAnchorSummary(reportFiles: string[]): string {
  if (reportFiles.length === 0) {
    return "Replay anchor not set";
  }
  if (reportFiles.length === 1) {
    return reportFiles[0] ?? "";
  }
  const preview = reportFiles.slice(0, 3).join(" | ");
  if (reportFiles.length <= 3) {
    return preview;
  }
  return `${reportFiles.length} selected: ${preview} ...`;
}

function isBuyFillMode(value: string): value is BuyFillMode {
  return value === "next_open" || value === "next_close";
}

function isEntryReferenceMode(value: string): value is EntryReferenceMode {
  return value === "raw_fill" || value === "buffered_fill";
}

function isCapacityRegimeMode(value: string): value is CapacityRegimeMode {
  return value === "off" || value === "enforce";
}

function isPositionSizingMode(value: string): value is PositionSizingMode {
  return value === "fixed" || value === "atr";
}

function isMomentumExhaustionMode(value: string): value is MomentumExhaustionMode {
  return value === "off" || value === "shadow" || value === "enforce";
}

function isIndustryFilterMode(value: string): value is IndustryFilterMode {
  return value === "off" || value === "shadow" || value === "enforce";
}

function formatEntryFilterModeLabel(mode: string): string {
  if (mode === "atr") return "atr (ATR only)";
  if (mode === "single") return "single (configured)";
  return mode;
}

function formatBuyFillModeLabel(mode: BuyFillMode): string {
  return mode === "next_open"
    ? "next_open (次日开盘成交)"
    : "next_close (次日收盘成交)";
}

function formatEntryReferenceModeLabel(mode: EntryReferenceMode): string {
  return mode === "raw_fill"
    ? "raw_fill (未加 buffer 的原始成交参考价; next_open 时即次日开盘)"
    : "buffered_fill (加 buffer 后的实际成交价)";
}

export default function Evaluation() {
  const options = useQuery<EvaluationOptionsResponse>({
    queryKey: ["eval-options"],
    queryFn: api.evalOptions,
  });
  const [command, setCommand] = useState<EvaluationCommand>("evaluate");
  const [selectedBuyFillModes, setSelectedBuyFillModes] = useState<
    BuyFillMode[]
  >(["next_open"]);
  const [selectedEntryReferenceModes, setSelectedEntryReferenceModes] =
    useState<EntryReferenceMode[]>(["raw_fill"]);
  const [fillBufferEnabled, setFillBufferEnabled] = useState(false);
  const [fillBufferPct, setFillBufferPct] = useState("0.02");
  const [selectedEntry, setSelectedEntry] = useState<string[]>([]);
  const [selectedExit, setSelectedExit] = useState<string[]>([]);
  const [mode, setMode] = useState<EvaluationMode>("annual");
  const [includeContinuous, setIncludeContinuous] = useState(false);
  const [years, setYears] = useState(DEFAULT_YEARS);
  const [months, setMonths] = useState("");
  const [customPeriods, setCustomPeriods] = useState("");
  const [launchDates, setLaunchDates] = useState<string[]>([]);
  const [exitConfirmDays, setExitConfirmDays] = useState("");
  const [entryFilterMode, setEntryFilterMode] =
    useState<EntryFilterMode>("atr");
  const [selectedFilterNames, setSelectedFilterNames] = useState<string[]>([]);
  const [verbose, setVerbose] = useState(false);
  const [enableOverlay, setEnableOverlay] = useState(false);
  const [selectedOverlayModes, setSelectedOverlayModes] = useState<string[]>([
    "off",
  ]);
  const [capacityRegimeMode, setCapacityRegimeMode] =
    useState<CapacityRegimeMode>("off");
  const [positionSizingMode, setPositionSizingMode] =
    useState<PositionSizingMode>("fixed");
  const [riskPerTradePct, setRiskPerTradePct] = useState("0.0108");
  const [atrStopMultiple, setAtrStopMultiple] = useState("0.6");
  const [atrRatioMin, setAtrRatioMin] = useState("");
  const [atrRatioMax, setAtrRatioMax] = useState("");
  const [momentumExhaustionMode, setMomentumExhaustionMode] =
    useState<MomentumExhaustionMode>("enforce");
  const [momentumExhaustionMaxScore, setMomentumExhaustionMaxScore] =
    useState("4.0");
  const [industryFilterMode, setIndustryFilterMode] =
    useState<IndustryFilterMode>("enforce");
  const [maxBuyPerIndustryPerDay, setMaxBuyPerIndustryPerDay] = useState("1");
  const [maxTotalPositionsPerIndustry, setMaxTotalPositionsPerIndustry] =
    useState("3");
  const [industryReferenceFile, setIndustryReferenceFile] =
    useState("data/jpx_final_list.csv");
  const [overrideProfileSizing, setOverrideProfileSizing] = useState(false);
  const [rankingMode, setRankingMode] = useState("prs_train");
  const [minTrainYears, setMinTrainYears] = useState("2");
  const [positionFile, setPositionFile] = useState("");
  const [selectedProfiles, setSelectedProfiles] = useState<string[]>([]);
  const [reportFilesText, setReportFilesText] = useState("");
  const [selectedQuickReplayReports, setSelectedQuickReplayReports] = useState<
    string[]
  >([]);
  const [selectedUniversePoolIds, setSelectedUniversePoolIds] = useState<string[]>([]);
  const [overrideStrategies, setOverrideStrategies] = useState(false);
  const [initializedFromOptions, setInitializedFromOptions] = useState(false);

  const exec = useStreamExec();
  const { confirm, dialog } = useConfirmDialog();

  const resolvedOutputDir = options.data?.defaults.output_dir;
  const reportDates = useQuery<string[]>({
    queryKey: ["report-dates"],
    queryFn: api.reportDates,
  });
  const productionEntry = options.data?.production.entry_strategy ?? "";
  const productionExit = options.data?.production.exit_strategy ?? "";
  const productionRankingStrategy =
    options.data?.production.ranking_strategy ?? "";
  const productionUniverse = options.data?.production.monitor_list_file ?? "";
  const productionReportPattern =
    options.data?.production.report_file_pattern ?? "";
  const isWalkForward = command === "walk-forward-evaluate";
  const isPosEvaluation = command === "pos-evaluation";
  const isReplayEvaluation = command === "replay-evaluation";
  const availableReplayReports = (reportDates.data ?? []).map((date) => ({
    date,
    path: productionReportPattern.includes("{date}")
      ? productionReportPattern.replace("{date}", date)
      : date,
  }));
  const replayReportFiles = parseStringList(
    [...selectedQuickReplayReports, ...parseStringList(reportFilesText)].join("\n"),
  );
  const singleReplayReportFile =
    replayReportFiles.length === 1 ? replayReportFiles[0] ?? "" : "";
  const replayAnchorSummary = formatReplayAnchorSummary(replayReportFiles);
  const replayUsesAutoStrategy = isReplayEvaluation && !overrideStrategies;
  const replayReportContext = useQuery<ReplayReportContext>({
    queryKey: ["eval-report-context", singleReplayReportFile],
    queryFn: () => api.evalReportContext(singleReplayReportFile.trim()),
    enabled:
      command === "replay-evaluation" &&
      singleReplayReportFile.trim().toLowerCase().endsWith(".md"),
    retry: false,
  });
  const showMonths = !isWalkForward && !isReplayEvaluation && mode === "monthly";
  const showCustomPeriods = !isWalkForward && !isReplayEvaluation && mode === "custom";
  const supportsContinuousCompanion = !isWalkForward && !isReplayEvaluation;
  const modeOptions = (options.data?.modes ?? []).filter(
    (item) => !isWalkForward || item === "annual" || item === "quarterly",
  );
  const showFilterNames =
    entryFilterMode === "single" ||
    entryFilterMode === "grid" ||
    entryFilterMode === "auto";
  const rankingModeOptions = options.data?.ranking_modes ?? ["prs_train"];
  const hasMultipleRankingModes = rankingModeOptions.length > 1;
  const parsedFillBufferPct = parseOptionalFloat(fillBufferPct);
  const fillBufferPctInvalid =
    parsedFillBufferPct === undefined ||
    parsedFillBufferPct < 0 ||
    parsedFillBufferPct >= 1;
  const parsedRiskPerTradePct = parseOptionalFloat(riskPerTradePct);
  const parsedAtrStopMultiple = parseOptionalFloat(atrStopMultiple);
  const parsedAtrRatioMin = parseOptionalFloat(atrRatioMin);
  const parsedAtrRatioMax = parseOptionalFloat(atrRatioMax);
  const parsedMomentumExhaustionMaxScore = parseOptionalFloat(
    momentumExhaustionMaxScore,
  );
  const includeSizingRuntimeOverrides = !isPosEvaluation || overrideProfileSizing;
  const atrSizingRuntimeEnabled =
    includeSizingRuntimeOverrides && positionSizingMode === "atr";
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
  const productionStockPoolCatalogFile =
    options.data?.production.stock_pool_catalog_file ?? "";
  const stockPools = options.data?.stock_pools ?? [];
  const selectedUniversePools = selectedUniversePoolIds
    .map((poolId) => stockPools.find((pool) => pool.id === poolId))
    .filter((pool): pool is StockPoolOption => Boolean(pool));
  const selectedUniverseSummary =
    selectedUniversePools.length > 0
      ? selectedUniversePools.map(formatStockPoolLabel).join(", ")
      : productionUniverse || "(production monitor list)";
  const buyFillModeOptions = (options.data?.buy_fill_modes ?? [
    "next_open",
    "next_close",
  ]).filter(isBuyFillMode);
  const entryReferenceModeOptions = (
    options.data?.entry_reference_modes ?? ["raw_fill", "buffered_fill"]
  ).filter(isEntryReferenceMode);
  const capacityRegimeModeOptions = (
    options.data?.capacity_regime_modes ?? ["off", "enforce"]
  ).filter(isCapacityRegimeMode);
  const executionBatchCount =
    selectedBuyFillModes.length * selectedEntryReferenceModes.length;
  const launchBatchCount =
    !isWalkForward && !isReplayEvaluation && launchDates.length > 0
      ? launchDates.length
      : 1;
  const executionSliceCount = executionBatchCount * launchBatchCount;
  const activeEntryCount = overrideStrategies
    ? selectedEntry.length
    : replayUsesAutoStrategy
      ? replayReportFiles.length > 0
        ? 1
        : 0
      : productionEntry
      ? 1
      : 0;
  const activeExitCount = overrideStrategies
    ? selectedExit.length
    : replayUsesAutoStrategy
      ? replayReportFiles.length > 0
        ? 1
        : 0
      : productionExit
      ? 1
      : 0;
  const strategyScopeLabel = overrideStrategies
    ? "override"
    : replayUsesAutoStrategy
      ? "per-report auto"
      : "production default";
  const modeLabel = isReplayEvaluation ? "replay" : mode;
  const sixColGridClass = "grid gap-3 md:grid-cols-2 xl:grid-cols-6 xl:auto-rows-fr";
  const summaryCardClassName =
    "rounded-lg border border-gray-800 bg-gray-900 px-4 py-3 min-h-[132px] h-full flex flex-col";
  const fieldCardClassName =
    "rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-3 min-h-[124px] h-full flex flex-col";
  const tallFieldCardClassName =
    "rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-3 min-h-[236px] h-full flex flex-col";
  const compactInputClassName =
    "h-10 w-full rounded border border-gray-700 bg-gray-800 px-3 text-sm";
  const compactTextareaClassName =
    "w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm";
  const compactCodeTextareaClassName = `${compactTextareaClassName} font-mono`;
  const compactLabelClassName =
    "text-xs uppercase tracking-wide text-gray-500 block mb-2";
  const launchDatesSpanClass = showCustomPeriods
    ? "xl:col-span-3"
    : showMonths
      ? "xl:col-span-4"
      : "xl:col-span-5";

  useEffect(() => {
    if (!options.data || initializedFromOptions) return;

    const defaults = options.data.defaults;
    setCommand((defaults.command as EvaluationCommand) ?? "evaluate");
    const defaultBuyFillModes = (defaults.buy_fill_modes ?? []).filter(
      isBuyFillMode,
    );
    setSelectedBuyFillModes(
      defaultBuyFillModes.length > 0
        ? defaultBuyFillModes
        : [
            isBuyFillMode(defaults.buy_fill_mode)
              ? defaults.buy_fill_mode
              : "next_open",
          ],
    );
    const defaultEntryReferenceModes = (
      defaults.entry_reference_modes ?? []
    ).filter(isEntryReferenceMode);
    setSelectedEntryReferenceModes(
      defaultEntryReferenceModes.length > 0
        ? defaultEntryReferenceModes
        : [
            isEntryReferenceMode(defaults.entry_reference_mode)
              ? defaults.entry_reference_mode
              : "raw_fill",
          ],
    );
    setFillBufferEnabled(Boolean(defaults.fill_buffer_enabled));
    setFillBufferPct(String(defaults.fill_buffer_pct ?? 0.02));
    setSelectedEntry(defaults.entry_strategies ?? []);
    setSelectedExit(defaults.exit_strategies ?? []);
    setMode((defaults.mode as EvaluationMode) ?? "annual");
    setIncludeContinuous(Boolean(defaults.include_continuous));
    setExitConfirmDays(
      defaults.exit_confirm_days !== null && defaults.exit_confirm_days !== undefined
        ? String(defaults.exit_confirm_days)
        : "",
    );
    setOverrideStrategies(Boolean(defaults.override_strategies));
    setEntryFilterMode(
      (defaults.entry_filter_mode as EntryFilterMode) ?? "atr",
    );
    setSelectedFilterNames(defaults.entry_filter_names ?? []);
    setEnableOverlay(Boolean(defaults.enable_overlay));
    setSelectedOverlayModes(defaults.overlay_modes ?? ["off"]);
    setCapacityRegimeMode(
      isCapacityRegimeMode(defaults.capacity_regime_mode)
        ? defaults.capacity_regime_mode
        : "off",
    );
    setPositionSizingMode(
      isPositionSizingMode(defaults.position_sizing_mode)
        ? defaults.position_sizing_mode
        : "fixed",
    );
    setRiskPerTradePct(String(defaults.risk_per_trade_pct ?? 0.0108));
    setAtrStopMultiple(String(defaults.atr_stop_multiple ?? 0.6));
    setAtrRatioMin(
      defaults.atr_ratio_min !== null && defaults.atr_ratio_min !== undefined
        ? String(defaults.atr_ratio_min)
        : "",
    );
    setAtrRatioMax(
      defaults.atr_ratio_max !== null && defaults.atr_ratio_max !== undefined
        ? String(defaults.atr_ratio_max)
        : "",
    );
    setMomentumExhaustionMode(
      isMomentumExhaustionMode(defaults.momentum_exhaustion_mode)
        ? defaults.momentum_exhaustion_mode
        : "enforce",
    );
    setMomentumExhaustionMaxScore(
      String(defaults.momentum_exhaustion_max_score ?? 4.0),
    );
    setIndustryFilterMode(
      isIndustryFilterMode(defaults.industry_filter_mode)
        ? defaults.industry_filter_mode
        : "enforce",
    );
    setMaxBuyPerIndustryPerDay(
      String(defaults.max_buy_per_industry_per_day ?? 1),
    );
    setMaxTotalPositionsPerIndustry(
      String(defaults.max_total_positions_per_industry ?? 3),
    );
    setIndustryReferenceFile(
      defaults.industry_reference_file ?? "data/jpx_final_list.csv",
    );
    setRankingMode(defaults.ranking_mode ?? "prs_train");
    setMinTrainYears(String(defaults.min_train_years ?? 2));
    setPositionFile(defaults.position_file ?? "");
    setSelectedProfiles(defaults.profile_names ?? []);
    setReportFilesText(defaults.report_file ?? "");
    setSelectedQuickReplayReports([]);
    setSelectedUniversePoolIds(defaults.universe_pool_ids ?? []);
    setLaunchDates([]);
    setInitializedFromOptions(true);
  }, [options.data, initializedFromOptions]);

  useEffect(() => {
    if (!showFilterNames && selectedFilterNames.length > 0) {
      setSelectedFilterNames([]);
      return;
    }
    if (entryFilterMode === "single" && selectedFilterNames.length > 1) {
      setSelectedFilterNames((current) => current.slice(0, 1));
    }
  }, [entryFilterMode, selectedFilterNames, showFilterNames]);

  useEffect(() => {
    if (isWalkForward && mode !== "annual" && mode !== "quarterly") {
      setMode("annual");
    }
  }, [isWalkForward, mode]);

  useEffect(() => {
    if (!isReplayEvaluation || replayReportFiles.length > 0) {
      return;
    }
    const latestReportDate = reportDates.data?.[0];
    if (!latestReportDate || !productionReportPattern.includes("{date}")) {
      return;
    }
    setReportFilesText(productionReportPattern.replace("{date}", latestReportDate));
  }, [
    isReplayEvaluation,
    productionReportPattern,
    reportDates.data,
    replayReportFiles.length,
  ]);

  async function handleRun() {
    if (selectedBuyFillModes.length === 0) {
      return;
    }
    if (selectedEntryReferenceModes.length === 0) {
      return;
    }
    if (isReplayEvaluation && replayReportFiles.length === 0) {
      return;
    }
    if (fillBufferPctInvalid) {
      return;
    }
    if (
      riskPerTradeInvalid ||
      atrStopMultipleInvalid ||
      atrRatioMinInvalid ||
      atrRatioMaxInvalid ||
      atrRatioRangeInvalid
    ) {
      return;
    }

    const normalizedFillBufferPct = parsedFillBufferPct ?? 0.02;
    const normalizedRiskPerTradePct = parsedRiskPerTradePct ?? 0.006;
    const normalizedAtrStopMultiple = parsedAtrStopMultiple ?? 2.0;
    const normalizedAtrRatioMin =
      atrRatioMin.trim() === "" ? null : parsedAtrRatioMin;
    const normalizedAtrRatioMax =
      atrRatioMax.trim() === "" ? null : parsedAtrRatioMax;
    const parsedMaxBuyPerIndustryPerDay = parseOptionalInt(
      maxBuyPerIndustryPerDay,
    );
    const parsedMaxTotalPositionsPerIndustry = parseOptionalInt(
      maxTotalPositionsPerIndustry,
    );
    const industryFilterInvalid =
      (maxBuyPerIndustryPerDay.trim() !== "" &&
        (parsedMaxBuyPerIndustryPerDay === undefined ||
          parsedMaxBuyPerIndustryPerDay <= 0)) ||
      (maxTotalPositionsPerIndustry.trim() !== "" &&
        (parsedMaxTotalPositionsPerIndustry === undefined ||
          parsedMaxTotalPositionsPerIndustry <= 0));
    if (industryFilterInvalid) {
      return;
    }
    const payload: Record<string, unknown> = {
      command,
      buy_fill_modes: selectedBuyFillModes,
      entry_reference_modes: selectedEntryReferenceModes,
      fill_buffer_enabled: fillBufferEnabled,
      fill_buffer_pct: normalizedFillBufferPct,
      capacity_regime_mode: capacityRegimeMode,
      override_strategies: overrideStrategies,
      entry_strategies:
        overrideStrategies && selectedEntry.length > 0 ? selectedEntry : undefined,
      exit_strategies:
        overrideStrategies && selectedExit.length > 0 ? selectedExit : undefined,
      years: isReplayEvaluation ? undefined : parseIntegerList(years),
      launch_dates:
        !isWalkForward && !isReplayEvaluation && launchDates.length > 0
          ? launchDates
          : undefined,
      exit_confirm_days: parseOptionalInt(exitConfirmDays),
      entry_filter_mode: entryFilterMode,
      entry_filter_names:
        showFilterNames && selectedFilterNames.length > 0
          ? selectedFilterNames
          : undefined,
      verbose,
      ranking_mode: rankingMode || undefined,
      universe_pool_ids:
        selectedUniversePoolIds.length > 0 ? selectedUniversePoolIds : undefined,
      atr_ratio_min: normalizedAtrRatioMin,
      atr_ratio_max: normalizedAtrRatioMax,
      momentum_exhaustion_mode: momentumExhaustionMode,
      momentum_exhaustion_max_score: parsedMomentumExhaustionMaxScore,
      momentum_exhaustion_threshold_method: "absolute",
      industry_filter_mode: industryFilterMode,
      max_buy_per_industry_per_day: parsedMaxBuyPerIndustryPerDay,
      max_total_positions_per_industry: parsedMaxTotalPositionsPerIndustry,
      industry_reference_file: industryReferenceFile.trim() || undefined,
    };

    if (supportsContinuousCompanion) {
      payload.include_continuous = includeContinuous;
    }

    if (includeSizingRuntimeOverrides) {
      payload.position_sizing_mode = positionSizingMode;
      if (positionSizingMode === "atr") {
        payload.risk_per_trade_pct = normalizedRiskPerTradePct;
        payload.atr_stop_multiple = normalizedAtrStopMultiple;
      }
    }

    if (!isReplayEvaluation) {
      payload.mode = mode;
    } else {
      payload.report_files = replayReportFiles.length > 0 ? replayReportFiles : undefined;
      payload.report_file = singleReplayReportFile || undefined;
    }

    if (isWalkForward) {
      payload.min_train_years = parseOptionalInt(minTrainYears) ?? 2;
    } else if (!isReplayEvaluation) {
      if (showMonths) {
        payload.months = parseIntegerList(months);
      }
      if (showCustomPeriods) {
        payload.custom_periods = customPeriods.trim() || undefined;
      }
    }

    if (isPosEvaluation) {
      payload.position_file = positionFile.trim() || undefined;
      payload.profile_names =
        selectedProfiles.length > 0 ? selectedProfiles : undefined;
      payload.overlay_modes =
        selectedOverlayModes.length > 0 ? selectedOverlayModes : undefined;
    } else {
      payload.enable_overlay = enableOverlay;
    }

    const ok = await confirm(
      `Run ${command}`,
      [
        `Command: ${command}`,
        `Buy Fill Modes: ${selectedBuyFillModes.join(", ")}`,
        `Entry Reference Modes: ${selectedEntryReferenceModes.join(", ")}`,
        `Fill Buffer: ${fillBufferEnabled ? `ON (${(normalizedFillBufferPct * 100).toFixed(2)}%)` : `OFF (${(normalizedFillBufferPct * 100).toFixed(2)}% configured)`}`,
        `Position Sizing: ${includeSizingRuntimeOverrides ? (positionSizingMode === "atr" ? `${positionSizingMode} | risk ${normalizedRiskPerTradePct} | stop ${normalizedAtrStopMultiple} ATR` : "fixed | ATR sizing params ignored") : "profile defaults"}`,
        `ATR% Filter Bounds: ${parsedAtrRatioMin ?? "-"} - ${parsedAtrRatioMax ?? "-"}`,
        `Momentum Exhaustion: ${momentumExhaustionMode} | max score ${parsedMomentumExhaustionMaxScore ?? "config default"}`,
        `Industry Filter: ${industryFilterMode} | daily ${parsedMaxBuyPerIndustryPerDay ?? "config default"} | total ${parsedMaxTotalPositionsPerIndustry ?? "config default"}`,
        `Execution: ${executionBatchCount} full run(s) across selected fill/reference combinations`,
        `Capacity Regime Mode: ${capacityRegimeMode}`,
        `Continuous Companion: ${supportsContinuousCompanion ? (includeContinuous ? "on" : "off") : "n/a"}`,
        isReplayEvaluation
          ? `Report Anchors: ${replayAnchorSummary}`
          : undefined,
        isWalkForward
          ? `Mode: ${mode} | Initial Train Years: ${payload.min_train_years}`
          : isReplayEvaluation
            ? "Mode: replay"
            : `Mode: ${mode}`,
        `Entry: ${overrideStrategies && selectedEntry.length > 0 ? selectedEntry.join(", ") : replayUsesAutoStrategy ? "per-report auto" : productionEntry}`,
        `Exit: ${overrideStrategies && selectedExit.length > 0 ? selectedExit.join(", ") : replayUsesAutoStrategy ? "per-report auto" : productionExit}`,
        `Signal Ranking Strategy: ${productionRankingStrategy || "(config default)"}`,
        `Universe: ${selectedUniverseSummary}`,
        `Output Root: ${resolvedOutputDir ?? "(config default)"}`,
        "Output Layout: YYYYMMDD/<strategy+runtime-signature+timestamp>/...",
      ].filter(Boolean).join("\n"),
    );
    if (!ok) return;
    await exec.execute("/evaluation/run", payload);
  }

  function toggleSelection<T extends string>(
    list: T[],
    setter: (v: T[]) => void,
    name: T,
    single = false,
  ) {
    if (single) {
      setter(list.includes(name) ? [] : [name]);
      return;
    }

    setter(list.includes(name) ? list.filter((n) => n !== name) : [...list, name]);
  }

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Strategy Evaluation</h2>
      {dialog}

      {options.isError && (
        <div className="rounded-lg border border-red-800 bg-red-950/40 px-4 py-3 text-sm text-red-200">
          Failed to load evaluation options: {String(options.error)}
        </div>
      )}

      <div className={sixColGridClass}>
        <div className={summaryCardClassName}>
          <div className="text-[11px] uppercase tracking-wide text-gray-500">
            Command
          </div>
          <div className="mt-2 text-base font-semibold text-white">{command}</div>
          <div className="mt-auto pt-3 text-xs text-gray-500">
            Current evaluation command in the active run form.
          </div>
        </div>

        <div className={summaryCardClassName}>
          <div className="text-[11px] uppercase tracking-wide text-gray-500">
            Mode
          </div>
          <div className="mt-2 text-base font-semibold text-white">{modeLabel}</div>
          <div className="mt-1 text-xs text-gray-400">
            ranking {rankingMode} / exit confirm {exitConfirmDays.trim() || "config"} / continuous {supportsContinuousCompanion ? (includeContinuous ? "on" : "off") : "n/a"}
          </div>
          <div className="mt-auto pt-3 text-xs text-gray-500">
            Replay uses the selected report anchors instead of period presets.
          </div>
        </div>

        <div className={summaryCardClassName}>
          <div className="text-[11px] uppercase tracking-wide text-gray-500">
            Execution
          </div>
          <div className="mt-2 text-base font-semibold text-white">{executionSliceCount} slices</div>
          <div className="mt-1 text-xs text-gray-400">
            fills {selectedBuyFillModes.length} / refs {selectedEntryReferenceModes.length} / launches {launchBatchCount}
          </div>
          <div className="mt-auto pt-3 text-xs text-gray-500">
            Before period expansion and strategy cross-product.
          </div>
        </div>

        <div className={summaryCardClassName}>
          <div className="text-[11px] uppercase tracking-wide text-gray-500">
            Strategy Scope
          </div>
          <div className="mt-2 text-base font-semibold text-white">{strategyScopeLabel}</div>
          <div className="mt-1 text-xs text-gray-400">
            entry {activeEntryCount} / exit {activeExitCount}
          </div>
          <div className="mt-auto pt-3 text-xs text-gray-500">
            {overrideStrategies
              ? "Comparing selected strategy families."
              : replayUsesAutoStrategy
                ? "Resolving entry/exit per selected report unless override is enabled."
                : "Using production defaults until override is enabled."}
          </div>
        </div>

        <div className={summaryCardClassName}>
          <div className="text-[11px] uppercase tracking-wide text-gray-500">
            Filters
          </div>
          <div className="mt-2 text-base font-semibold text-white">
            {entryFilterMode} / {capacityRegimeMode}
          </div>
          <div className="mt-1 text-xs text-gray-400">
            named {selectedFilterNames.length} / overlay {isPosEvaluation ? selectedOverlayModes.join(", ") : enableOverlay ? "on" : "off"}
          </div>
          <div className="mt-auto pt-3 text-xs text-gray-500">
            Sizing {isPosEvaluation && !overrideProfileSizing ? "profile" : positionSizingMode} / ATR% {atrRatioMin || "-"}-{atrRatioMax || "-"}.
          </div>
        </div>

        <div className={summaryCardClassName}>
          <div className="text-[11px] uppercase tracking-wide text-gray-500">
            Output
          </div>
          <div className="mt-2 text-sm font-semibold text-white break-all">
            {resolvedOutputDir ?? "(config default output dir)"}
          </div>
          <div className="mt-1 text-xs text-gray-400 break-all">
            {isReplayEvaluation
              ? replayAnchorSummary
              : productionUniverse || "Production monitor list not configured"}
          </div>
          <div className="mt-auto pt-3 text-xs text-gray-500">
            YYYYMMDD / strategy+filters+signature+timestamp
          </div>
        </div>
      </div>

      <div className="space-y-4">
        {/* Config panel */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 lg:p-5 space-y-4">
          <h3 className="font-semibold text-blue-400">Configuration</h3>

          <div className={sixColGridClass}>
            <div className={fieldCardClassName}>
              <label className={compactLabelClassName}>Command</label>
              <select
                value={command}
                onChange={(e) => setCommand(e.target.value as EvaluationCommand)}
                className={compactInputClassName}
              >
                {(options.data?.commands ?? []).map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </div>

            <div className={fieldCardClassName}>
              <label className={compactLabelClassName}>
                {isReplayEvaluation ? "Replay Anchor" : "Mode"}
              </label>
              {isReplayEvaluation ? (
                <div className="rounded border border-gray-800 bg-gray-900/80 px-3 py-2 text-sm text-gray-300 break-all flex-1">
                  {replayAnchorSummary || "Choose one or more report markdown paths below."}
                </div>
              ) : (
                <>
                  <select
                    value={mode}
                    onChange={(e) => setMode(e.target.value as EvaluationMode)}
                    className={compactInputClassName}
                  >
                    {modeOptions.map((item) => (
                      <option key={item}>{item}</option>
                    ))}
                  </select>
                  {isWalkForward && mode === "quarterly" && (
                    <p className="mt-2 text-[11px] text-gray-500">
                      Quarterly walk-forward expands within selected years.
                    </p>
                  )}
                </>
              )}
            </div>

            <div className={fieldCardClassName}>
              <label className={compactLabelClassName}>Train Ranking Mode</label>
              {hasMultipleRankingModes ? (
                <select
                  value={rankingMode}
                  onChange={(e) => setRankingMode(e.target.value)}
                  className={compactInputClassName}
                >
                  {rankingModeOptions.map((item) => (
                    <option key={item}>{item}</option>
                  ))}
                </select>
              ) : (
                <div className="rounded border border-gray-800 bg-gray-900/80 px-3 py-2 text-sm text-gray-300 h-10 flex items-center">
                  prs_train
                </div>
              )}
              <p className="mt-2 text-[11px] text-gray-500">
                Ranking strategy name itself stays fixed to production.
              </p>
            </div>

            <div className={fieldCardClassName}>
              <label className={compactLabelClassName}>Exit Confirm Days</label>
              <input
                value={exitConfirmDays}
                onChange={(e) => setExitConfirmDays(e.target.value)}
                placeholder="Use config default when blank"
                className={compactInputClassName}
              />
            </div>

            <div className={fieldCardClassName}>
              <div className="flex items-center justify-between gap-3 mb-2">
                <label className="text-xs uppercase tracking-wide text-gray-500">
                  Fill Buffer
                </label>
                <input
                  type="checkbox"
                  checked={fillBufferEnabled}
                  onChange={(e) => setFillBufferEnabled(e.target.checked)}
                />
              </div>
              <input
                value={fillBufferPct}
                onChange={(e) => setFillBufferPct(e.target.value)}
                placeholder="0.02"
                className={compactInputClassName}
              />
              <p className="mt-2 text-[11px] text-gray-500">
                buy raw × (1 + buffer), sell raw × (1 - buffer)
              </p>
              {!fillBufferEnabled &&
                selectedEntryReferenceModes.includes("buffered_fill") && (
                  <p className="mt-2 text-[11px] text-yellow-300">
                    buffered_fill currently collapses to raw_fill.
                  </p>
                )}
              {fillBufferPctInvalid && (
                <p className="mt-2 text-[11px] text-red-400">
                  Enter a valid ratio between 0 and 1.
                </p>
              )}
            </div>

            <div className={fieldCardClassName}>
              <label className={compactLabelClassName}>Run Flags</label>
              <div className="space-y-2 text-sm text-gray-300">
                {supportsContinuousCompanion && (
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={includeContinuous}
                      onChange={(e) => setIncludeContinuous(e.target.checked)}
                    />
                    Include Continuous Companion
                  </label>
                )}
                {!isPosEvaluation && (
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={enableOverlay}
                      onChange={(e) => setEnableOverlay(e.target.checked)}
                    />
                    Enable Overlay
                  </label>
                )}
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={verbose}
                    onChange={(e) => setVerbose(e.target.checked)}
                  />
                  Verbose Output
                </label>
                {supportsContinuousCompanion && (
                  <p className="mt-2 text-[11px] text-gray-500">
                    Adds one full-span companion run after segmented annual or quarterly periods.
                  </p>
                )}
              </div>
            </div>
          </div>

          <div className={sixColGridClass}>
            <div className={`${tallFieldCardClassName} xl:col-span-2`}>
              <label className={compactLabelClassName}>
                Buy Fill Modes ({selectedBuyFillModes.length} selected)
              </label>
              <p className="mb-2 text-xs text-gray-500">
                Select one or both. The run will execute the full evaluation set for each selected fill mode.
              </p>
              <CheckboxList
                options={buyFillModeOptions}
                selected={selectedBuyFillModes}
                onToggle={(name) => {
                  if (!isBuyFillMode(name)) return;
                  toggleSelection(
                    selectedBuyFillModes,
                    setSelectedBuyFillModes,
                    name,
                  );
                }}
              />
              {selectedBuyFillModes.length === 0 && (
                <p className="mt-2 text-xs text-red-400">
                  Select at least one fill mode to run evaluation.
                </p>
              )}
              {selectedBuyFillModes.length > 0 && (
                <p className="mt-2 text-xs text-gray-500">
                  Active: {selectedBuyFillModes.map(formatBuyFillModeLabel).join(", ")}
                </p>
              )}
            </div>

            <div className={`${tallFieldCardClassName} xl:col-span-2`}>
              <label className={compactLabelClassName}>
                Entry Reference Modes ({selectedEntryReferenceModes.length} selected)
              </label>
              <p className="mb-2 text-xs text-gray-500">
                Select at least one. Each selected mode runs the full evaluation set once per buy fill mode.
              </p>
              <CheckboxList
                options={entryReferenceModeOptions}
                selected={selectedEntryReferenceModes}
                onToggle={(name) => {
                  if (!isEntryReferenceMode(name)) return;
                  toggleSelection(
                    selectedEntryReferenceModes,
                    setSelectedEntryReferenceModes,
                    name,
                  );
                }}
              />
              {selectedEntryReferenceModes.length === 0 && (
                <p className="mt-2 text-xs text-red-400">
                  Select at least one entry reference mode to run evaluation.
                </p>
              )}
              {selectedEntryReferenceModes.length > 0 && (
                <p className="mt-2 text-xs text-gray-500">
                  Active: {selectedEntryReferenceModes.map(formatEntryReferenceModeLabel).join(", ")}
                </p>
              )}
            </div>

            <div className={fieldCardClassName}>
              <label className={compactLabelClassName}>Capacity Regime</label>
                <select
                  value={capacityRegimeMode}
                  onChange={(e) =>
                    setCapacityRegimeMode(e.target.value as CapacityRegimeMode)
                  }
                  className={compactInputClassName}
                >
                  {capacityRegimeModeOptions.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              <p className="mt-2 text-[11px] text-gray-500">
                Tier-based position and liquidity constraints for evaluation.
              </p>
            </div>

            <div className={fieldCardClassName}>
              <label className={compactLabelClassName}>Entry Filter Mode</label>
                <select
                  value={entryFilterMode}
                  onChange={(e) =>
                    setEntryFilterMode(e.target.value as EntryFilterMode)
                  }
                  className={compactInputClassName}
                >
                  {(options.data?.entry_filter_modes ?? []).map((item) => (
                    <option key={item} value={item}>
                      {formatEntryFilterModeLabel(item)}
                    </option>
                  ))}
                </select>
              <p className="mt-2 text-[11px] text-gray-500">
                {entryFilterMode === "atr"
                  ? "ATR-only"
                  : `${selectedFilterNames.length} named filters currently selected.`}
              </p>
            </div>
          </div>

          <div className={sixColGridClass}>
            <div className={fieldCardClassName}>
              <label className={compactLabelClassName}>Position Sizing</label>
              <select
                value={positionSizingMode}
                onChange={(e) => setPositionSizingMode(e.target.value as PositionSizingMode)}
                className={compactInputClassName}
              >
                <option value="fixed">fixed</option>
                <option value="atr">atr</option>
              </select>
              {isPosEvaluation && (
                <label className="mt-2 flex items-center gap-2 text-[11px] text-gray-400">
                  <input
                    type="checkbox"
                    checked={overrideProfileSizing}
                    onChange={(e) => setOverrideProfileSizing(e.target.checked)}
                  />
                  Override profiles
                </label>
              )}
            </div>

            <div className={fieldCardClassName}>
              <label className={compactLabelClassName}>Risk Per Trade</label>
              <input
                value={riskPerTradePct}
                onChange={(e) => setRiskPerTradePct(e.target.value)}
                disabled={!atrSizingRuntimeEnabled}
                className={`${compactInputClassName} disabled:cursor-not-allowed disabled:bg-gray-900 disabled:text-gray-500`}
              />
              {riskPerTradeInvalid && (
                <p className="mt-2 text-[11px] text-red-400">Enter a positive ratio.</p>
              )}
            </div>

            <div className={fieldCardClassName}>
              <label className={compactLabelClassName}>ATR Stop Multiple</label>
              <input
                value={atrStopMultiple}
                onChange={(e) => setAtrStopMultiple(e.target.value)}
                disabled={!atrSizingRuntimeEnabled}
                className={`${compactInputClassName} disabled:cursor-not-allowed disabled:bg-gray-900 disabled:text-gray-500`}
              />
              {atrStopMultipleInvalid && (
                <p className="mt-2 text-[11px] text-red-400">Enter a positive multiple.</p>
              )}
            </div>

            <div className={fieldCardClassName}>
              <label className={compactLabelClassName}>ATR% Min</label>
              <input
                value={atrRatioMin}
                onChange={(e) => setAtrRatioMin(e.target.value)}
                className={compactInputClassName}
              />
            </div>

            <div className={fieldCardClassName}>
              <label className={compactLabelClassName}>ATR% Max</label>
              <input
                value={atrRatioMax}
                onChange={(e) => setAtrRatioMax(e.target.value)}
                className={compactInputClassName}
              />
              {atrRatioRangeInvalid && (
                <p className="mt-2 text-[11px] text-red-400">Min must be no greater than max.</p>
              )}
            </div>

            <div className={fieldCardClassName}>
              <label className={compactLabelClassName}>Momentum Exhaustion</label>
              <select
                value={momentumExhaustionMode}
                onChange={(e) =>
                  setMomentumExhaustionMode(e.target.value as MomentumExhaustionMode)
                }
                className={compactInputClassName}
              >
                <option value="enforce">enforce</option>
                <option value="shadow">shadow</option>
                <option value="off">off</option>
              </select>
            </div>

            <div className={fieldCardClassName}>
              <label className={compactLabelClassName}>Momentum Max Score</label>
              <input
                value={momentumExhaustionMaxScore}
                onChange={(e) => setMomentumExhaustionMaxScore(e.target.value)}
                className={compactInputClassName}
              />
            </div>

            <div className={fieldCardClassName}>
              <label className={compactLabelClassName}>Industry Filter</label>
              <select
                value={industryFilterMode}
                onChange={(e) =>
                  setIndustryFilterMode(e.target.value as IndustryFilterMode)
                }
                className={compactInputClassName}
              >
                <option value="enforce">enforce</option>
                <option value="shadow">shadow</option>
                <option value="off">off</option>
              </select>
            </div>

            <div className={fieldCardClassName}>
              <label className={compactLabelClassName}>Industry Daily Cap</label>
              <input
                value={maxBuyPerIndustryPerDay}
                onChange={(e) => setMaxBuyPerIndustryPerDay(e.target.value)}
                className={compactInputClassName}
              />
            </div>

            <div className={fieldCardClassName}>
              <label className={compactLabelClassName}>Industry Total Cap</label>
              <input
                value={maxTotalPositionsPerIndustry}
                onChange={(e) => setMaxTotalPositionsPerIndustry(e.target.value)}
                className={compactInputClassName}
              />
            </div>

            <div className={fieldCardClassName}>
              <label className={compactLabelClassName}>Industry CSV</label>
              <input
                value={industryReferenceFile}
                onChange={(e) => setIndustryReferenceFile(e.target.value)}
                className={compactInputClassName}
              />
            </div>

            <div className={`${fieldCardClassName} justify-center`}>
              <div className="text-xs text-gray-400">
                {isPosEvaluation && !overrideProfileSizing
                  ? "Profile sizing is active for pos-evaluation."
                  : positionSizingMode === "atr"
                    ? "Runtime ATR sizing will use risk and stop settings."
                    : "Fixed sizing ignores ATR risk and stop settings."}
              </div>
            </div>
          </div>

          {isReplayEvaluation ? (
            <div className={sixColGridClass}>
              <div className={`${tallFieldCardClassName} xl:col-span-6`}>
                <label className={compactLabelClassName}>Replay Report Anchors</label>
                <div className="grid gap-3 xl:grid-cols-3">
                  <div className="xl:col-span-2">
                    <label className="text-[11px] text-gray-500 block mb-1">Replay Report Files</label>
                    <textarea
                      value={reportFilesText}
                      onChange={(e) => setReportFilesText(e.target.value)}
                      placeholder={"G:\\My Drive\\AI-Stock-Sync\\reports\\2026-05-15.md\nG:\\My Drive\\AI-Stock-Sync\\reports\\2026-05-19.md"}
                      rows={4}
                      className={compactTextareaClassName}
                    />
                    {replayReportFiles.length === 0 && (
                      <p className="mt-2 text-[11px] text-red-400">
                        Replay requires at least one report markdown path.
                      </p>
                    )}
                    {replayReportFiles.length > 1 && (
                      <p className="mt-2 text-[11px] text-gray-500">
                        Batch mode will run one replay per selected report markdown.
                      </p>
                    )}
                  </div>

                  <div>
                    <label className="text-[11px] text-gray-500 block mb-1">Quick Select Existing Reports</label>
                    <div className="max-h-44 overflow-y-auto rounded border border-gray-800 bg-gray-950/40 p-2">
                      {availableReplayReports.length > 0 ? (
                        <div className="space-y-1">
                          {availableReplayReports.map((item) => (
                            <label
                              key={item.path}
                              className="flex items-start gap-2 rounded px-1.5 py-1 text-xs text-gray-300 cursor-pointer hover:bg-gray-900/60 hover:text-white"
                            >
                              <input
                                type="checkbox"
                                checked={selectedQuickReplayReports.includes(item.path)}
                                onChange={() =>
                                  toggleSelection(
                                    selectedQuickReplayReports,
                                    setSelectedQuickReplayReports,
                                    item.path,
                                  )
                                }
                                className="mt-0.5 rounded"
                              />
                              <span className="flex flex-col">
                                <span>{item.date}</span>
                                <span className="text-[11px] text-gray-500 break-all">
                                  {item.path}
                                </span>
                              </span>
                            </label>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-gray-500">No existing reports available.</p>
                      )}
                    </div>
                  </div>
                </div>

                <div className="mt-3 grid gap-3 xl:grid-cols-2">
                  <p className="text-[11px] text-gray-500">
                    Replay reconstructs historical production state from each selected report date, then continues from the next trading day.
                  </p>

                  {singleReplayReportFile && replayReportContext.data ? (
                    <div className="rounded border border-emerald-900 bg-emerald-950/30 px-3 py-2 text-xs text-emerald-200">
                      Detected strategy combo: {replayReportContext.data.entry_strategy} × {replayReportContext.data.exit_strategy}
                      {!overrideStrategies && (
                        <span className="block mt-1 text-emerald-300/90">
                          Backend will use this combo automatically unless you enable strategy override.
                        </span>
                      )}
                    </div>
                  ) : replayReportFiles.length > 1 ? (
                    <div className="rounded border border-blue-900 bg-blue-950/30 px-3 py-2 text-xs text-blue-200">
                      {overrideStrategies
                        ? "Manual strategy override will be applied to all selected report anchors."
                        : "Batch replay will resolve each report's own entry/exit combo on the backend."}
                    </div>
                  ) : replayReportContext.isError && singleReplayReportFile ? (
                    <p className="text-xs text-yellow-300">
                      Failed to extract strategy combo from the selected report. Replay will fall back to configured defaults unless you enable manual override.
                    </p>
                  ) : null}
                </div>
              </div>
            </div>
          ) : isWalkForward ? (
            <div className={sixColGridClass}>
              <div className={`${fieldCardClassName} xl:col-span-3`}>
                <label className={compactLabelClassName}>Years</label>
                <textarea
                  value={years}
                  onChange={(e) => setYears(e.target.value)}
                  rows={2}
                  className={compactTextareaClassName}
                />
              </div>

              <div className={`${fieldCardClassName} xl:col-span-3`}>
                <label className={compactLabelClassName}>Initial Train Years</label>
                <input
                  value={minTrainYears}
                  onChange={(e) => setMinTrainYears(e.target.value)}
                  className={compactInputClassName}
                />
                <p className="mt-2 text-[11px] text-gray-500">
                  Quarterly mode: 2 means the first 8 quarters train the model.
                </p>
              </div>
            </div>
          ) : (
            <div className={sixColGridClass}>
              <div className={fieldCardClassName}>
                <label className={compactLabelClassName}>Years</label>
                <textarea
                  value={years}
                  onChange={(e) => setYears(e.target.value)}
                  rows={2}
                  className={compactTextareaClassName}
                />
              </div>

              {showMonths && (
                <div className={fieldCardClassName}>
                  <label className={compactLabelClassName}>Months</label>
                  <input
                    value={months}
                    onChange={(e) => setMonths(e.target.value)}
                    className={compactInputClassName}
                  />
                </div>
              )}

              {showCustomPeriods && (
                <div className={`${tallFieldCardClassName} xl:col-span-2`}>
                  <label className={compactLabelClassName}>Custom Periods JSON</label>
                  <textarea
                    value={customPeriods}
                    onChange={(e) => setCustomPeriods(e.target.value)}
                    rows={4}
                    placeholder='[["2024-Q1", "2024-01-01", "2024-03-31"]]'
                    className={compactCodeTextareaClassName}
                  />
                </div>
              )}

              <div className={`${tallFieldCardClassName} ${launchDatesSpanClass}`}>
                <label className={compactLabelClassName}>Launch Dates</label>
                <MultiDatePicker
                  value={launchDates}
                  onChange={setLaunchDates}
                  className="h-full border-0 bg-transparent p-0"
                />
                <p className="mt-2 text-[11px] text-gray-500">
                  Each selected date expands the run set once.
                </p>
              </div>
            </div>
          )}

          <div className={sixColGridClass}>
            <div className={`${fieldCardClassName} xl:col-span-2`}>
              <label className={compactLabelClassName}>Universe</label>
              <div className="text-sm text-gray-300 flex-1">
                <div className="text-[11px] uppercase tracking-wide text-gray-500">Production Monitor List</div>
                <div className="mt-2 break-all">{productionUniverse || "Not configured"}</div>
                <div className="mt-3 text-[11px] uppercase tracking-wide text-gray-500">Stock Pool Catalog</div>
                <div className="mt-2 break-all text-xs text-gray-400">
                  {productionStockPoolCatalogFile || "Not configured"}
                </div>
              </div>
            </div>

            <div className={`${fieldCardClassName} xl:col-span-2`}>
              <label className={compactLabelClassName}>Production Defaults</label>
              <div className="space-y-2 text-sm text-gray-300 flex-1">
                <div>
                  <div className="text-[11px] uppercase tracking-wide text-gray-500">Entry Strategy</div>
                  <div className="mt-1 break-all">{productionEntry || "Not configured"}</div>
                </div>
                <div>
                  <div className="text-[11px] uppercase tracking-wide text-gray-500">Exit Strategy</div>
                  <div className="mt-1 break-all">{productionExit || "Not configured"}</div>
                </div>
                <div>
                  <div className="text-[11px] uppercase tracking-wide text-gray-500">Signal Ranking Strategy</div>
                  <div className="mt-1 break-all">{productionRankingStrategy || "Not configured"}</div>
                </div>
              </div>
            </div>

            <div className={`${fieldCardClassName} xl:col-span-2`}>
              <label className={compactLabelClassName}>Output Root</label>
              <p className="text-sm text-gray-200 break-all flex-1">
                {resolvedOutputDir ?? "(config default output dir)"}
              </p>
              <p className="mt-2 text-[11px] text-gray-500">
                Results are stored automatically as YYYYMMDD / strategy+filters+signature+timestamp.
              </p>
            </div>
          </div>

          <div className={tallFieldCardClassName}>
            <label className={compactLabelClassName}>
              Optional Stock Pools ({selectedUniversePoolIds.length} selected)
            </label>
            <StockPoolChecklist
              options={stockPools}
              selected={selectedUniversePoolIds}
              onToggle={(poolId) =>
                toggleSelection(
                  selectedUniversePoolIds,
                  setSelectedUniversePoolIds,
                  poolId,
                )
              }
            />
            <p className="mt-2 text-[11px] text-gray-500">
              Leave this empty to preserve the current production monitor list. Selecting multiple pools expands the evaluation run through the existing multi-universe CLI path.
            </p>
          </div>

          {showFilterNames && (
            <div className={tallFieldCardClassName}>
              <label className={compactLabelClassName}>
                Entry Filter Names ({selectedFilterNames.length} selected)
              </label>
              <CheckboxList
                options={options.data?.entry_filter_names ?? []}
                selected={selectedFilterNames}
                onToggle={(name) =>
                  toggleSelection(
                    selectedFilterNames,
                    setSelectedFilterNames,
                    name,
                    entryFilterMode === "single",
                  )
                }
                emptyText="No named entry filters found in config."
              />
            </div>
          )}

          <div className="rounded-lg border border-gray-800 bg-gray-950/30 px-3 py-3 min-h-[76px] flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
            <label className="flex items-center gap-2 text-sm text-gray-300">
              <input
                type="checkbox"
                checked={overrideStrategies}
                onChange={(e) => setOverrideStrategies(e.target.checked)}
              />
              Override / Compare Strategies
            </label>
            <p className="text-xs text-gray-500">
              {overrideStrategies
                ? `${selectedEntry.length} entry and ${selectedExit.length} exit strategies selected for this run.`
                : replayUsesAutoStrategy
                  ? "Backend will resolve each selected report's entry/exit combo unless override is enabled."
                  : "Using production entry/exit defaults until override is enabled."}
            </p>
          </div>

          {overrideStrategies && (
            <div className={sixColGridClass}>
              <div className="xl:col-span-3 h-full">
                <StrategyMultiSelect
                  label="Entry Strategies"
                  options={options.data?.entry_strategies ?? []}
                  selected={selectedEntry}
                  onChange={setSelectedEntry}
                  searchPlaceholder="Search entry strategies..."
                />
              </div>

              <div className="xl:col-span-3 h-full">
                <ExitStrategyFamilyBuilder
                  selected={selectedExit}
                  onChange={setSelectedExit}
                  defaultStrategy={productionExit || options.data?.defaults.exit_strategies?.[0]}
                  className={tallFieldCardClassName}
                />
              </div>
            </div>
          )}

          {isPosEvaluation ? (
            <div className={sixColGridClass}>
              <div className={`${tallFieldCardClassName} xl:col-span-2`}>
                <label className={compactLabelClassName}>
                  Position File
                </label>
                <input
                  value={positionFile}
                  onChange={(e) => setPositionFile(e.target.value)}
                  className={compactInputClassName}
                />
              </div>

              <div className={`${tallFieldCardClassName} xl:col-span-2`}>
                <label className={compactLabelClassName}>
                  Position Profiles ({selectedProfiles.length} selected)
                </label>
                <CheckboxList
                  options={options.data?.position_profiles ?? []}
                  selected={selectedProfiles}
                  onToggle={(name) =>
                    toggleSelection(selectedProfiles, setSelectedProfiles, name)
                  }
                  emptyText="No position profiles found in the configured position file."
                />
              </div>

              <div className={`${tallFieldCardClassName} xl:col-span-2`}>
                <label className={compactLabelClassName}>
                  Overlay Modes ({selectedOverlayModes.length} selected)
                </label>
                <CheckboxList
                  options={options.data?.overlay_modes ?? []}
                  selected={selectedOverlayModes}
                  onToggle={(name) =>
                    toggleSelection(
                      selectedOverlayModes,
                      setSelectedOverlayModes,
                      name,
                    )
                  }
                />
              </div>
            </div>
          ) : null}

          <div className={sixColGridClass}>
            <div className={`${fieldCardClassName} xl:col-span-5 justify-center`}>
              <div className="text-xs uppercase tracking-wide text-gray-500">
                Run Summary
              </div>
              <div className="mt-2 flex flex-wrap gap-2 text-xs text-gray-300">
                <span className="rounded-full border border-gray-700 px-2 py-1">
                  {executionBatchCount} fill/ref slices
                </span>
                <span className="rounded-full border border-gray-700 px-2 py-1">
                  {launchBatchCount} launch set(s)
                </span>
                <span className="rounded-full border border-gray-700 px-2 py-1">
                  {activeEntryCount} entry
                </span>
                <span className="rounded-full border border-gray-700 px-2 py-1">
                  {activeExitCount} exit
                </span>
                <span className="rounded-full border border-gray-700 px-2 py-1">
                  filter {entryFilterMode}
                </span>
                <span className="rounded-full border border-gray-700 px-2 py-1">
                  buffer {fillBufferEnabled ? "on" : "off"}
                </span>
              </div>
            </div>

            <div className={`${fieldCardClassName} xl:col-span-1 justify-center`}>
              <button
                onClick={handleRun}
                disabled={
                  exec.running ||
                  selectedBuyFillModes.length === 0 ||
                  selectedEntryReferenceModes.length === 0 ||
                  fillBufferPctInvalid ||
                  riskPerTradeInvalid ||
                  atrStopMultipleInvalid ||
                  atrRatioRangeInvalid
                }
                className="h-full min-h-[78px] px-4 py-3 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded text-sm w-full"
              >
                Run {command}
              </button>
            </div>
          </div>

          {exec.lines.length > 0 && (
            <LogOutput
              lines={exec.lines}
              running={exec.running}
              exitCode={exec.exitCode}
            />
          )}
        </div>
      </div>
    </div>
  );
}

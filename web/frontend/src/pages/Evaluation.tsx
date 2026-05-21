import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import StrategyMultiSelect from "../components/StrategyMultiSelect";
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
type EntryFilterMode = "off" | "single" | "grid" | "auto";
type BuyFillMode = "next_open" | "next_close";
type EntryReferenceMode = "raw_fill" | "buffered_fill";
type CapacityRegimeMode = "off" | "enforce";

interface EvaluationDefaults {
  command: string;
  mode: string;
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
  position_file: string;
  profile_names: string[];
  report_file: string;
  min_train_years: number;
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
    report_file_pattern: string;
  };
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

function isBuyFillMode(value: string): value is BuyFillMode {
  return value === "next_open" || value === "next_close";
}

function isEntryReferenceMode(value: string): value is EntryReferenceMode {
  return value === "raw_fill" || value === "buffered_fill";
}

function isCapacityRegimeMode(value: string): value is CapacityRegimeMode {
  return value === "off" || value === "enforce";
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
  const [years, setYears] = useState(DEFAULT_YEARS);
  const [months, setMonths] = useState("");
  const [customPeriods, setCustomPeriods] = useState("");
  const [launchDates, setLaunchDates] = useState<string[]>([]);
  const [exitConfirmDays, setExitConfirmDays] = useState("");
  const [entryFilterMode, setEntryFilterMode] =
    useState<EntryFilterMode>("off");
  const [selectedFilterNames, setSelectedFilterNames] = useState<string[]>([]);
  const [verbose, setVerbose] = useState(false);
  const [enableOverlay, setEnableOverlay] = useState(false);
  const [selectedOverlayModes, setSelectedOverlayModes] = useState<string[]>([
    "off",
  ]);
  const [capacityRegimeMode, setCapacityRegimeMode] =
    useState<CapacityRegimeMode>("off");
  const [rankingMode, setRankingMode] = useState("prs_train");
  const [minTrainYears, setMinTrainYears] = useState("2");
  const [positionFile, setPositionFile] = useState("");
  const [selectedProfiles, setSelectedProfiles] = useState<string[]>([]);
  const [reportFile, setReportFile] = useState("");
  const [overrideStrategies, setOverrideStrategies] = useState(false);
  const [autoAppliedReplayReportFile, setAutoAppliedReplayReportFile] =
    useState("");
  const [initializedFromOptions, setInitializedFromOptions] = useState(false);

  const exec = useStreamExec();
  const { confirm, dialog } = useConfirmDialog();

  const resolvedOutputDir = options.data?.defaults.output_dir;
  const reportDates = useQuery<string[]>({
    queryKey: ["report-dates"],
    queryFn: api.reportDates,
  });
  const isWalkForward = command === "walk-forward-evaluate";
  const isPosEvaluation = command === "pos-evaluation";
  const isReplayEvaluation = command === "replay-evaluation";
  const replayReportContext = useQuery<ReplayReportContext>({
    queryKey: ["eval-report-context", reportFile],
    queryFn: () => api.evalReportContext(reportFile.trim()),
    enabled:
      command === "replay-evaluation" &&
      reportFile.trim().toLowerCase().endsWith(".md"),
    retry: false,
  });
  const showMonths = !isWalkForward && !isReplayEvaluation && mode === "monthly";
  const showCustomPeriods = !isWalkForward && !isReplayEvaluation && mode === "custom";
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
  const productionEntry = options.data?.production.entry_strategy ?? "";
  const productionExit = options.data?.production.exit_strategy ?? "";
  const productionRankingStrategy =
    options.data?.production.ranking_strategy ?? "";
  const productionUniverse = options.data?.production.monitor_list_file ?? "";
  const productionReportPattern =
    options.data?.production.report_file_pattern ?? "";
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
    : productionEntry
      ? 1
      : 0;
  const activeExitCount = overrideStrategies
    ? selectedExit.length
    : productionExit
      ? 1
      : 0;
  const strategyScopeLabel = overrideStrategies ? "override" : "production default";
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
    setExitConfirmDays(
      defaults.exit_confirm_days !== null && defaults.exit_confirm_days !== undefined
        ? String(defaults.exit_confirm_days)
        : "",
    );
    setOverrideStrategies(Boolean(defaults.override_strategies));
    setEntryFilterMode(
      (defaults.entry_filter_mode as EntryFilterMode) ?? "off",
    );
    setSelectedFilterNames(defaults.entry_filter_names ?? []);
    setEnableOverlay(Boolean(defaults.enable_overlay));
    setSelectedOverlayModes(defaults.overlay_modes ?? ["off"]);
    setCapacityRegimeMode(
      isCapacityRegimeMode(defaults.capacity_regime_mode)
        ? defaults.capacity_regime_mode
        : "off",
    );
    setRankingMode(defaults.ranking_mode ?? "prs_train");
    setMinTrainYears(String(defaults.min_train_years ?? 2));
    setPositionFile(defaults.position_file ?? "");
    setSelectedProfiles(defaults.profile_names ?? []);
    setReportFile(defaults.report_file ?? "");
    setLaunchDates([]);
    setInitializedFromOptions(true);
  }, [options.data, initializedFromOptions]);

  useEffect(() => {
    if (entryFilterMode === "single" && selectedFilterNames.length > 1) {
      setSelectedFilterNames((current) => current.slice(0, 1));
    }
  }, [entryFilterMode, selectedFilterNames]);

  useEffect(() => {
    if (isWalkForward && mode !== "annual" && mode !== "quarterly") {
      setMode("annual");
    }
  }, [isWalkForward, mode]);

  useEffect(() => {
    if (!isReplayEvaluation || reportFile.trim()) {
      return;
    }
    const latestReportDate = reportDates.data?.[0];
    if (!latestReportDate || !productionReportPattern.includes("{date}")) {
      return;
    }
    setReportFile(productionReportPattern.replace("{date}", latestReportDate));
  }, [
    isReplayEvaluation,
    productionReportPattern,
    reportDates.data,
    reportFile,
  ]);

  useEffect(() => {
    if (!isReplayEvaluation || !replayReportContext.data) {
      return;
    }
    if (autoAppliedReplayReportFile === replayReportContext.data.report_file) {
      return;
    }

    setSelectedEntry([replayReportContext.data.entry_strategy]);
    setSelectedExit([replayReportContext.data.exit_strategy]);
    setOverrideStrategies(true);
    setAutoAppliedReplayReportFile(replayReportContext.data.report_file);
  }, [
    autoAppliedReplayReportFile,
    isReplayEvaluation,
    replayReportContext.data,
  ]);

  async function handleRun() {
    if (selectedBuyFillModes.length === 0) {
      return;
    }
    if (selectedEntryReferenceModes.length === 0) {
      return;
    }
    if (isReplayEvaluation && !reportFile.trim()) {
      return;
    }
    if (fillBufferPctInvalid) {
      return;
    }

    const normalizedFillBufferPct = parsedFillBufferPct ?? 0.02;
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
    };

    if (!isReplayEvaluation) {
      payload.mode = mode;
    } else {
      payload.report_file = reportFile.trim() || undefined;
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
        `Execution: ${executionBatchCount} full run(s) across selected fill/reference combinations`,
        `Capacity Regime Mode: ${capacityRegimeMode}`,
        isReplayEvaluation
          ? `Report Anchor: ${reportFile.trim() || "(missing)"}`
          : undefined,
        isWalkForward
          ? `Mode: ${mode} | Initial Train Years: ${payload.min_train_years}`
          : isReplayEvaluation
            ? "Mode: replay"
            : `Mode: ${mode}`,
        `Entry: ${overrideStrategies && selectedEntry.length > 0 ? selectedEntry.join(", ") : productionEntry}`,
        `Exit: ${overrideStrategies && selectedExit.length > 0 ? selectedExit.join(", ") : productionExit}`,
        `Signal Ranking Strategy: ${productionRankingStrategy || "(config default)"}`,
        `Universe: ${productionUniverse || "(production monitor list)"}`,
        `Output Root: ${resolvedOutputDir ?? "(config default)"}`,
        "Output Layout: YYYYMMDD/<entry+exit+timestamp>/...",
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
            ranking {rankingMode} / exit confirm {exitConfirmDays.trim() || "config"}
          </div>
          <div className="mt-auto pt-3 text-xs text-gray-500">
            Replay uses the selected report anchor instead of period presets.
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
            Fill buffer {fillBufferEnabled ? "enabled" : "disabled"} at {((parsedFillBufferPct ?? 0) * 100).toFixed(2)}%.
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
              ? reportFile.trim() || "Replay anchor not set"
              : productionUniverse || "Production monitor list not configured"}
          </div>
          <div className="mt-auto pt-3 text-xs text-gray-500">
            YYYYMMDD / entry+exit+timestamp
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
                  {reportFile.trim() || "Choose a report markdown path below."}
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
                    <option key={item}>{item}</option>
                  ))}
                </select>
              <p className="mt-2 text-[11px] text-gray-500">
                {selectedFilterNames.length} named filters currently selected.
              </p>
            </div>
          </div>

          {isReplayEvaluation ? (
            <div className={sixColGridClass}>
              <div className={`${tallFieldCardClassName} xl:col-span-6`}>
                <label className={compactLabelClassName}>Replay Report Anchor</label>
                <div className="grid gap-3 xl:grid-cols-3">
                  <div className="xl:col-span-2">
                    <label className="text-[11px] text-gray-500 block mb-1">Replay Report File</label>
                    <input
                      value={reportFile}
                      onChange={(e) => setReportFile(e.target.value)}
                      placeholder="G:\\My Drive\\AI-Stock-Sync\\reports\\2026-05-15.md"
                      className={compactInputClassName}
                    />
                    {!reportFile.trim() && (
                      <p className="mt-2 text-[11px] text-red-400">
                        Replay requires a concrete report markdown path.
                      </p>
                    )}
                  </div>

                  <div>
                    <label className="text-[11px] text-gray-500 block mb-1">Quick Select Existing Reports</label>
                    <select
                      value={
                        (reportDates.data ?? []).some(
                          (date) =>
                            productionReportPattern.includes("{date}") &&
                            productionReportPattern.replace("{date}", date) === reportFile,
                        )
                          ? reportFile
                          : ""
                      }
                      onChange={(e) => setReportFile(e.target.value)}
                      className={compactInputClassName}
                    >
                      <option value="">Use typed path</option>
                      {(reportDates.data ?? []).map((date) => {
                        const resolvedPath = productionReportPattern.includes("{date}")
                          ? productionReportPattern.replace("{date}", date)
                          : date;
                        return (
                          <option key={date} value={resolvedPath}>
                            {date}
                          </option>
                        );
                      })}
                    </select>
                  </div>
                </div>

                <div className="mt-3 grid gap-3 xl:grid-cols-2">
                  <p className="text-[11px] text-gray-500">
                    Replay reconstructs historical production state from the selected report date, then continues from the next trading day.
                  </p>

                  {replayReportContext.data ? (
                    <div className="rounded border border-emerald-900 bg-emerald-950/30 px-3 py-2 text-xs text-emerald-200">
                      Auto-applied strategy combo: {replayReportContext.data.entry_strategy} × {replayReportContext.data.exit_strategy}
                    </div>
                  ) : replayReportContext.isError && reportFile.trim() ? (
                    <p className="text-xs text-yellow-300">
                      Failed to extract strategy combo from the selected report. Current strategy selection was left unchanged.
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
                Results are stored automatically as YYYYMMDD / entry+exit+timestamp.
              </p>
            </div>
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
                <StrategyMultiSelect
                  label="Exit Strategies"
                  options={options.data?.exit_strategies ?? []}
                  selected={selectedExit}
                  onChange={setSelectedExit}
                  searchPlaceholder="Search exit strategies..."
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
                  fillBufferPctInvalid
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

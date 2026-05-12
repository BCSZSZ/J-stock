import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useConfirmDialog } from "../components/ConfirmDialog";
import LogOutput from "../components/LogOutput";
import { useStreamExec } from "../hooks/useStreamExec";

type EvaluationCommand =
  | "evaluate"
  | "pos-evaluation"
  | "walk-forward-evaluate";
type EvaluationMode = "annual" | "quarterly" | "monthly" | "custom";
type EntryFilterMode = "off" | "single" | "grid" | "auto";

interface EvaluationDefaults {
  command: string;
  mode: string;
  override_strategies: boolean;
  entry_strategies: string[];
  exit_strategies: string[];
  ranking_mode: string;
  ranking_strategies: string[];
  entry_filter_mode: string;
  entry_filter_names: string[];
  enable_overlay: boolean;
  overlay_modes: string[];
  exit_confirm_days: number | null;
  output_dir: string;
  universe_files: string[];
  position_file: string;
  profile_names: string[];
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
  ranking_modes: string[];
  position_profiles: string[];
  production: {
    entry_strategy: string;
    exit_strategy: string;
    ranking_strategy: string;
    monitor_list_file: string;
  };
  defaults: EvaluationDefaults;
}

interface EvaluationResultFile {
  name: string;
  type: string;
  size: string;
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
    <div className="max-h-40 overflow-y-auto space-y-0.5 rounded border border-gray-800 bg-gray-950/40 p-2">
      {options.map((option) => (
        <label
          key={option}
          className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer hover:text-white"
        >
          <input
            type="checkbox"
            checked={selected.includes(option)}
            onChange={() => onToggle(option)}
            className="rounded"
          />
          <span className="break-all">{option}</span>
        </label>
      ))}
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

export default function Evaluation() {
  const queryClient = useQueryClient();
  const options = useQuery<EvaluationOptionsResponse>({
    queryKey: ["eval-options"],
    queryFn: api.evalOptions,
  });
  const [command, setCommand] = useState<EvaluationCommand>("evaluate");
  const [selectedEntry, setSelectedEntry] = useState<string[]>([]);
  const [selectedExit, setSelectedExit] = useState<string[]>([]);
  const [mode, setMode] = useState<EvaluationMode>("annual");
  const [years, setYears] = useState(DEFAULT_YEARS);
  const [months, setMonths] = useState("");
  const [customPeriods, setCustomPeriods] = useState("");
  const [exitConfirmDays, setExitConfirmDays] = useState("");
  const [entryFilterMode, setEntryFilterMode] =
    useState<EntryFilterMode>("off");
  const [selectedFilterNames, setSelectedFilterNames] = useState<string[]>([]);
  const [verbose, setVerbose] = useState(false);
  const [enableOverlay, setEnableOverlay] = useState(false);
  const [selectedOverlayModes, setSelectedOverlayModes] = useState<string[]>([
    "off",
  ]);
  const [rankingMode, setRankingMode] = useState("target20");
  const [selectedRankingStrategies, setSelectedRankingStrategies] = useState<
    string[]
  >([]);
  const [minTrainYears, setMinTrainYears] = useState("2");
  const [positionFile, setPositionFile] = useState("");
  const [selectedProfiles, setSelectedProfiles] = useState<string[]>([]);
  const [overrideStrategies, setOverrideStrategies] = useState(false);
  const [initializedFromOptions, setInitializedFromOptions] = useState(false);

  const exec = useStreamExec();
  const { confirm, dialog } = useConfirmDialog();

  const [viewResult, setViewResult] = useState<Record<
    string,
    unknown
  > | null>(null);

  const resolvedOutputDir = options.data?.defaults.output_dir;
  const results = useQuery<EvaluationResultFile[]>({
    queryKey: ["eval-results", resolvedOutputDir],
    queryFn: () => api.evalResults(resolvedOutputDir),
  });

  const isWalkForward = command === "walk-forward-evaluate";
  const isPosEvaluation = command === "pos-evaluation";
  const showMonths = !isWalkForward && mode === "monthly";
  const showCustomPeriods = !isWalkForward && mode === "custom";
  const showFilterNames =
    entryFilterMode === "single" ||
    entryFilterMode === "grid" ||
    entryFilterMode === "auto";
  const productionEntry = options.data?.production.entry_strategy ?? "";
  const productionExit = options.data?.production.exit_strategy ?? "";
  const productionUniverse = options.data?.production.monitor_list_file ?? "";

  useEffect(() => {
    if (!options.data || initializedFromOptions) return;

    const defaults = options.data.defaults;
    setCommand((defaults.command as EvaluationCommand) ?? "evaluate");
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
    setRankingMode(defaults.ranking_mode ?? "target20");
    setSelectedRankingStrategies(defaults.ranking_strategies ?? []);
    setMinTrainYears(String(defaults.min_train_years ?? 2));
    setPositionFile(defaults.position_file ?? "");
    setSelectedProfiles(defaults.profile_names ?? []);
    setInitializedFromOptions(true);
  }, [options.data, initializedFromOptions]);

  useEffect(() => {
    if (entryFilterMode === "single" && selectedFilterNames.length > 1) {
      setSelectedFilterNames((current) => current.slice(0, 1));
    }
  }, [entryFilterMode, selectedFilterNames]);

  async function handleRun() {
    const payload: Record<string, unknown> = {
      command,
      override_strategies: overrideStrategies,
      entry_strategies:
        overrideStrategies && selectedEntry.length > 0 ? selectedEntry : undefined,
      exit_strategies:
        overrideStrategies && selectedExit.length > 0 ? selectedExit : undefined,
      years: parseIntegerList(years),
      exit_confirm_days: parseOptionalInt(exitConfirmDays),
      entry_filter_mode: entryFilterMode,
      entry_filter_names:
        showFilterNames && selectedFilterNames.length > 0
          ? selectedFilterNames
          : undefined,
      verbose,
      ranking_mode: rankingMode || undefined,
      ranking_strategies:
        selectedRankingStrategies.length > 0
          ? selectedRankingStrategies
          : undefined,
    };

    if (isWalkForward) {
      payload.min_train_years = parseOptionalInt(minTrainYears) ?? 2;
    } else {
      payload.mode = mode;
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
        isWalkForward ? `Min Train Years: ${payload.min_train_years}` : `Mode: ${mode}`,
          `Entry: ${overrideStrategies && selectedEntry.length > 0 ? selectedEntry.join(", ") : productionEntry}`,
          `Exit: ${overrideStrategies && selectedExit.length > 0 ? selectedExit.join(", ") : productionExit}`,
          `Universe: ${productionUniverse || "(production monitor list)"}`,
        `Output Root: ${resolvedOutputDir ?? "(config default)"}`,
        "Output Layout: YYYYMMDD/<entry+exit+timestamp>/...",
      ].join("\n"),
    );
    if (!ok) return;
    await exec.execute("/evaluation/run", payload);
    await queryClient.invalidateQueries({ queryKey: ["eval-results"] });
  }

  async function handleViewResult(filename: string) {
    const data = await api.evalResult(filename, resolvedOutputDir);
    setViewResult(data);
  }

  function toggleSelection(
    list: string[],
    setter: (v: string[]) => void,
    name: string,
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

      {results.isError && (
        <div className="rounded-lg border border-yellow-800 bg-yellow-950/40 px-4 py-3 text-sm text-yellow-200">
          Failed to load result files: {String(results.error)}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Config panel */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-4">
          <h3 className="font-semibold text-blue-400">Configuration</h3>

          <div>
            <label className="text-xs text-gray-500 block mb-1">Command</label>
            <select
              value={command}
              onChange={(e) => setCommand(e.target.value as EvaluationCommand)}
              className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm w-full"
            >
              {(options.data?.commands ?? []).map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </div>

          {!isWalkForward && (
            <div>
              <label className="text-xs text-gray-500 block mb-1">Mode</label>
              <select
                value={mode}
                onChange={(e) => setMode(e.target.value as EvaluationMode)}
                className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm w-full"
              >
                {(options.data?.modes ?? []).map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </div>
          )}

          <div>
            <label className="text-xs text-gray-500 block mb-1">
              Years (comma or newline separated)
            </label>
            <textarea
              value={years}
              onChange={(e) => setYears(e.target.value)}
              rows={2}
              className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm w-full"
            />
          </div>

          {showMonths && (
            <div>
              <label className="text-xs text-gray-500 block mb-1">
                Months (comma or newline separated)
              </label>
              <input
                value={months}
                onChange={(e) => setMonths(e.target.value)}
                className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm w-full"
              />
            </div>
          )}

          {showCustomPeriods && (
            <div>
              <label className="text-xs text-gray-500 block mb-1">
                Custom Periods JSON
              </label>
              <textarea
                value={customPeriods}
                onChange={(e) => setCustomPeriods(e.target.value)}
                rows={4}
                placeholder='[["2024-Q1", "2024-01-01", "2024-03-31"]]'
                className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm w-full font-mono"
              />
            </div>
          )}

          {isWalkForward && (
            <div>
              <label className="text-xs text-gray-500 block mb-1">
                Min Train Years
              </label>
              <input
                value={minTrainYears}
                onChange={(e) => setMinTrainYears(e.target.value)}
                className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm w-full"
              />
            </div>
          )}

          <div>
            <label className="text-xs text-gray-500 block mb-1">
              Universe
            </label>
            <div className="rounded border border-gray-800 bg-gray-950/40 px-3 py-2 text-sm text-gray-300">
              <div className="text-xs uppercase tracking-wide text-gray-500">
                Production Monitor List
              </div>
              <div className="mt-1 break-all">{productionUniverse || "Not configured"}</div>
            </div>
          </div>

          <div>
            <label className="text-xs text-gray-500 block mb-1">
              Production Strategies
            </label>
            <div className="space-y-2 rounded border border-gray-800 bg-gray-950/40 px-3 py-3 text-sm text-gray-300">
              <div>
                <div className="text-xs uppercase tracking-wide text-gray-500">Entry Strategy</div>
                <div className="mt-1 break-all">{productionEntry || "Not configured"}</div>
              </div>
              <div>
                <div className="text-xs uppercase tracking-wide text-gray-500">Exit Strategy</div>
                <div className="mt-1 break-all">{productionExit || "Not configured"}</div>
              </div>
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm text-gray-300">
            <input
              type="checkbox"
              checked={overrideStrategies}
              onChange={(e) => setOverrideStrategies(e.target.checked)}
            />
            Override / Compare Strategies
          </label>

          {overrideStrategies && (
            <>
              <div>
                <label className="text-xs text-gray-500 block mb-1">
                  Entry Strategies ({selectedEntry.length} selected)
                </label>
                <CheckboxList
                  options={options.data?.entry_strategies ?? []}
                  selected={selectedEntry}
                  onToggle={(name) =>
                    toggleSelection(selectedEntry, setSelectedEntry, name)
                  }
                />
              </div>

              <div>
                <label className="text-xs text-gray-500 block mb-1">
                  Exit Strategies ({selectedExit.length} selected)
                </label>
                <CheckboxList
                  options={options.data?.exit_strategies ?? []}
                  selected={selectedExit}
                  onToggle={(name) =>
                    toggleSelection(selectedExit, setSelectedExit, name)
                  }
                />
              </div>
            </>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 block mb-1">
                Ranking Mode
              </label>
              <select
                value={rankingMode}
                onChange={(e) => setRankingMode(e.target.value)}
                className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm w-full"
              >
                {(options.data?.ranking_modes ?? []).map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-xs text-gray-500 block mb-1">
                Exit Confirm Days
              </label>
              <input
                value={exitConfirmDays}
                onChange={(e) => setExitConfirmDays(e.target.value)}
                placeholder="Use config default when blank"
                className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm w-full"
              />
            </div>
          </div>

          <div>
            <label className="text-xs text-gray-500 block mb-1">
              Ranking Strategies ({selectedRankingStrategies.length} selected)
            </label>
            <CheckboxList
              options={options.data?.ranking_strategies ?? []}
              selected={selectedRankingStrategies}
              onToggle={(name) =>
                toggleSelection(
                  selectedRankingStrategies,
                  setSelectedRankingStrategies,
                  name,
                )
              }
            />
          </div>

          <div>
            <label className="text-xs text-gray-500 block mb-1">
              Entry Filter Mode
            </label>
            <select
              value={entryFilterMode}
              onChange={(e) =>
                setEntryFilterMode(e.target.value as EntryFilterMode)
              }
              className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm w-full"
            >
              {(options.data?.entry_filter_modes ?? []).map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </div>

          {showFilterNames && (
            <div>
              <label className="text-xs text-gray-500 block mb-1">
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

          <div className="rounded-lg border border-gray-800 bg-gray-950/50 px-3 py-2">
            <p className="text-xs text-gray-500 mb-1">Output Root</p>
            <p className="text-sm text-gray-200 break-all">
              {resolvedOutputDir ?? "(config default output dir)"}
            </p>
            <p className="mt-1 text-xs text-gray-500">
              Results are stored automatically as YYYYMMDD / entry+exit+timestamp.
            </p>
          </div>

          {isPosEvaluation ? (
            <>
              <div>
                <label className="text-xs text-gray-500 block mb-1">
                  Position File
                </label>
                <input
                  value={positionFile}
                  onChange={(e) => setPositionFile(e.target.value)}
                  className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm w-full"
                />
              </div>

              <div>
                <label className="text-xs text-gray-500 block mb-1">
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

              <div>
                <label className="text-xs text-gray-500 block mb-1">
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
            </>
          ) : (
            <label className="flex items-center gap-2 text-sm text-gray-300">
              <input
                type="checkbox"
                checked={enableOverlay}
                onChange={(e) => setEnableOverlay(e.target.checked)}
              />
              Enable Overlay
            </label>
          )}

          <label className="flex items-center gap-2 text-sm text-gray-300">
            <input
              type="checkbox"
              checked={verbose}
              onChange={(e) => setVerbose(e.target.checked)}
            />
            Verbose Output
          </label>

          <button
            onClick={handleRun}
            disabled={exec.running}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded text-sm w-full"
          >
            Run {command}
          </button>

          {exec.lines.length > 0 && (
            <LogOutput
              lines={exec.lines}
              running={exec.running}
              exitCode={exec.exitCode}
            />
          )}
        </div>

        {/* Results panel */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-4">
          <h3 className="font-semibold text-green-400">Past Results</h3>
          <p className="text-xs text-gray-500 break-all">
            Browsing: {resolvedOutputDir ?? "(config default output dir)"}
          </p>
          <div className="max-h-96 overflow-y-auto space-y-1">
            {(results.data ?? []).length === 0 && (
              <p className="text-xs text-gray-500">No result files found.</p>
            )}
            {(results.data ?? []).map((f) => (
              <button
                key={f.name}
                onClick={() => handleViewResult(f.name)}
                className="w-full text-left px-3 py-1.5 text-xs rounded hover:bg-gray-800 text-gray-300 flex justify-between"
              >
                <span className="truncate">{f.name}</span>
                <span className="text-gray-600 ml-2">{f.type}</span>
              </button>
            ))}
          </div>
          {viewResult && (
            <div className="mt-4">
              <div className="flex justify-between items-center mb-2">
                <span className="text-sm font-medium">
                  {(viewResult.name as string) ?? "Result"}
                </span>
                <button
                  onClick={() => setViewResult(null)}
                  className="text-xs text-gray-500 hover:text-gray-300"
                >
                  Close
                </button>
              </div>
              {viewResult.type === "csv" ? (
                <div className="overflow-x-auto max-h-60 text-xs">
                  <pre className="text-gray-300">
                    {JSON.stringify(viewResult.data, null, 2).slice(0, 5000)}
                  </pre>
                </div>
              ) : (
                <div className="prose prose-invert prose-sm max-h-60 overflow-y-auto">
                  <pre className="text-gray-300 whitespace-pre-wrap text-xs">
                    {viewResult.content as string}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

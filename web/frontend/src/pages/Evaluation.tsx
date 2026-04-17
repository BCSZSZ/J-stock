import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useConfirmDialog } from "../components/ConfirmDialog";
import LogOutput from "../components/LogOutput";
import { useStreamExec } from "../hooks/useStreamExec";

export default function Evaluation() {
  const options = useQuery({
    queryKey: ["eval-options"],
    queryFn: api.evalOptions,
  });
  const results = useQuery({
    queryKey: ["eval-results"],
    queryFn: api.evalResults,
  });

  const [selectedEntry, setSelectedEntry] = useState<string[]>([]);
  const [selectedExit, setSelectedExit] = useState<string[]>([]);
  const [mode, setMode] = useState("annual");
  const [years, setYears] = useState("2022,2023,2024,2025");
  const [overlay, setOverlay] = useState(false);

  const exec = useStreamExec();
  const { confirm, dialog } = useConfirmDialog();

  const [viewResult, setViewResult] = useState<Record<
    string,
    unknown
  > | null>(null);

  async function handleRun() {
    if (selectedEntry.length === 0 || selectedExit.length === 0) return;
    const ok = await confirm(
      "Run Evaluation",
      `Entry: ${selectedEntry.join(", ")}\nExit: ${selectedExit.join(", ")}\nMode: ${mode}`,
    );
    if (!ok) return;
    exec.execute("/evaluation/run", {
      entry_strategies: selectedEntry,
      exit_strategies: selectedExit,
      mode,
      years: years.split(",").map((y) => parseInt(y.trim())),
      enable_overlay: overlay,
    });
  }

  async function handleViewResult(filename: string) {
    const data = await api.evalResult(filename);
    setViewResult(data);
  }

  function toggleStrategy(
    list: string[],
    setter: (v: string[]) => void,
    name: string,
  ) {
    setter(
      list.includes(name)
        ? list.filter((n) => n !== name)
        : [...list, name],
    );
  }

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Strategy Evaluation</h2>
      {dialog}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Config panel */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-4">
          <h3 className="font-semibold text-blue-400">Configuration</h3>

          {/* Mode */}
          <div>
            <label className="text-xs text-gray-500 block mb-1">Mode</label>
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm w-full"
            >
              {(options.data?.modes ?? []).map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </div>

          {/* Years */}
          <div>
            <label className="text-xs text-gray-500 block mb-1">
              Years (comma-separated)
            </label>
            <input
              value={years}
              onChange={(e) => setYears(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm w-full"
            />
          </div>

          {/* Entry strategies */}
          <div>
            <label className="text-xs text-gray-500 block mb-1">
              Entry Strategies ({selectedEntry.length} selected)
            </label>
            <div className="max-h-40 overflow-y-auto space-y-0.5">
              {(options.data?.entry_strategies ?? []).map((s) => (
                <label
                  key={s}
                  className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer hover:text-white"
                >
                  <input
                    type="checkbox"
                    checked={selectedEntry.includes(s)}
                    onChange={() =>
                      toggleStrategy(selectedEntry, setSelectedEntry, s)
                    }
                    className="rounded"
                  />
                  {s}
                </label>
              ))}
            </div>
          </div>

          {/* Exit strategies */}
          <div>
            <label className="text-xs text-gray-500 block mb-1">
              Exit Strategies ({selectedExit.length} selected)
            </label>
            <div className="max-h-40 overflow-y-auto space-y-0.5">
              {(options.data?.exit_strategies ?? []).map((s) => (
                <label
                  key={s}
                  className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer hover:text-white"
                >
                  <input
                    type="checkbox"
                    checked={selectedExit.includes(s)}
                    onChange={() =>
                      toggleStrategy(selectedExit, setSelectedExit, s)
                    }
                    className="rounded"
                  />
                  {s}
                </label>
              ))}
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm text-gray-300">
            <input
              type="checkbox"
              checked={overlay}
              onChange={(e) => setOverlay(e.target.checked)}
            />
            Enable Overlay
          </label>

          <button
            onClick={handleRun}
            disabled={
              exec.running ||
              selectedEntry.length === 0 ||
              selectedExit.length === 0
            }
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded text-sm w-full"
          >
            Run Evaluation
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
          <div className="max-h-96 overflow-y-auto space-y-1">
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

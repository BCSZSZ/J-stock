import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export default function Strategies() {
  const { data, isLoading } = useQuery({
    queryKey: ["strategies"],
    queryFn: api.strategies,
  });
  const [selected, setSelected] = useState<Record<string, unknown> | null>(
    null,
  );
  const [tab, setTab] = useState<"entry" | "exit">("entry");

  if (isLoading) return <div className="text-gray-500">Loading...</div>;

  const list = tab === "entry" ? (data?.entry ?? []) : (data?.exit ?? []);

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Strategies</h2>

      {/* Tabs */}
      <div className="flex gap-2">
        <button
          onClick={() => setTab("entry")}
          className={`px-4 py-2 rounded text-sm ${
            tab === "entry"
              ? "bg-blue-600 text-white"
              : "bg-gray-800 text-gray-400 hover:text-white"
          }`}
        >
          Entry ({data?.entry.length ?? 0})
        </button>
        <button
          onClick={() => setTab("exit")}
          className={`px-4 py-2 rounded text-sm ${
            tab === "exit"
              ? "bg-blue-600 text-white"
              : "bg-gray-800 text-gray-400 hover:text-white"
          }`}
        >
          Exit ({data?.exit.length ?? 0})
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Strategy list */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 max-h-[600px] overflow-y-auto">
          <div className="space-y-1">
            {list.map((s) => (
              <button
                key={s.name as string}
                onClick={() => setSelected(s)}
                className={`w-full text-left px-3 py-2 rounded text-sm transition-colors ${
                  selected?.name === s.name
                    ? "bg-blue-600/20 text-blue-400"
                    : "text-gray-300 hover:bg-gray-800"
                }`}
              >
                <div className="font-medium">{s.name as string}</div>
                <div className="text-xs text-gray-500 truncate">
                  {(s.description as string) ?? ""}
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Detail panel */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
          {selected ? (
            <div className="space-y-4">
              <h3 className="text-lg font-semibold text-blue-400">
                {selected.name as string}
              </h3>
              <div className="flex gap-2">
                <span className="px-2 py-0.5 bg-gray-800 rounded text-xs text-gray-400">
                  {selected.type as string}
                </span>
                <span className="px-2 py-0.5 bg-gray-800 rounded text-xs text-gray-400">
                  {selected.category as string}
                </span>
              </div>
              <p className="text-sm text-gray-300">
                {selected.description as string}
              </p>
              {selected.docstring ? (
                <pre className="text-xs text-gray-400 bg-gray-950 rounded p-3 whitespace-pre-wrap max-h-40 overflow-y-auto">
                  {String(selected.docstring)}
                </pre>
              ) : null}
              {((selected.parameters as Array<Record<string, string>>) ?? []).length >
                0 && (
                <div>
                  <h4 className="text-sm font-medium text-gray-400 mb-2">
                    Parameters
                  </h4>
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-gray-500 border-b border-gray-800">
                        <th className="py-1 px-2 text-left">Name</th>
                        <th className="py-1 px-2 text-left">Type</th>
                        <th className="py-1 px-2 text-left">Default</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(
                        selected.parameters as Array<Record<string, string>>
                      ).map((p) => (
                        <tr
                          key={p.name}
                          className="border-b border-gray-800/30"
                        >
                          <td className="py-1 px-2 text-blue-300">
                            {p.name}
                          </td>
                          <td className="py-1 px-2 text-gray-500">
                            {p.type ?? "—"}
                          </td>
                          <td className="py-1 px-2 text-gray-400">
                            {p.default ?? "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <div className="text-xs text-gray-600">
                Module: {selected.module as string}
              </div>
            </div>
          ) : (
            <div className="text-gray-500 text-sm">
              Select a strategy to view details
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

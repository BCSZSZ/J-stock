import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useTickerNames } from "../hooks/useTickerNames";

export default function Stocks() {
  const { data: tickers, isLoading } = useQuery({
    queryKey: ["tickers"],
    queryFn: api.tickers,
  });
  const { data: monitorList } = useQuery({
    queryKey: ["monitor-list"],
    queryFn: api.monitorList,
  });
  const names = useTickerNames();
  const [search, setSearch] = useState("");
  const [filterMonitor, setFilterMonitor] = useState(false);

  const monitorSet = useMemo(
    () => new Set(monitorList ?? []),
    [monitorList],
  );

  const filtered = useMemo(() => {
    let list = tickers ?? [];
    if (filterMonitor) {
      list = list.filter((t) => monitorSet.has(t));
    }
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(
        (t) =>
          t.includes(q) ||
          (names[t] ?? "").toLowerCase().includes(q),
      );
    }
    return list;
  }, [tickers, search, filterMonitor, monitorSet, names]);

  if (isLoading) return <div className="text-gray-500">Loading...</div>;

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Stocks</h2>

      <div className="flex gap-3 items-center">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search ticker or name..."
          className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm w-64"
        />
        <label className="flex items-center gap-1.5 text-sm text-gray-400 cursor-pointer">
          <input
            type="checkbox"
            checked={filterMonitor}
            onChange={(e) => setFilterMonitor(e.target.checked)}
            className="accent-blue-500"
          />
          Monitor list only
        </label>
        <span className="text-xs text-gray-500">
          {filtered.length} / {(tickers ?? []).length} tickers
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 border-b border-gray-800">
              <th className="py-2 px-3">Ticker</th>
              <th className="py-2 px-3">Name</th>
              <th className="py-2 px-3">Monitor</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((t) => (
              <tr
                key={t}
                className="border-b border-gray-800/50 hover:bg-gray-800/30"
              >
                <td className="py-2 px-3">
                  <Link
                    to={`/stock/${t}`}
                    className="text-blue-400 hover:underline font-medium"
                  >
                    {t}
                  </Link>
                </td>
                <td className="py-2 px-3 text-gray-300">
                  {names[t] ?? ""}
                </td>
                <td className="py-2 px-3">
                  {monitorSet.has(t) && (
                    <span className="text-green-400 text-xs">●</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

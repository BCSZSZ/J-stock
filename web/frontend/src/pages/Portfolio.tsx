import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useTickerNames } from "../hooks/useTickerNames";

export default function Portfolio() {
  const { data, isLoading } = useQuery({
    queryKey: ["portfolio"],
    queryFn: api.portfolio,
  });
  const names = useTickerNames();

  if (isLoading) return <div className="text-gray-500">Loading...</div>;

  const groups = data?.groups ?? [];

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Portfolio</h2>
      <p className="text-xs text-gray-500">
        Last updated: {data?.last_updated ?? "—"}
      </p>

      {groups.map((g) => {
        const invested = g.positions.reduce(
          (sum, p) => sum + p.entry_price * p.quantity,
          0,
        );
        return (
          <div
            key={g.id}
            className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-4"
          >
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold">{g.name}</h3>
              <div className="text-right">
                <div className="text-sm text-gray-400">
                  Cash: <span className="text-green-400">¥{g.cash.toLocaleString()}</span>
                </div>
                <div className="text-xs text-gray-500">
                  Initial: ¥{g.initial_capital.toLocaleString()} | Invested: ¥
                  {invested.toLocaleString()}
                </div>
              </div>
            </div>

            {g.positions.length === 0 ? (
              <p className="text-gray-500 text-sm">No positions</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-gray-500 border-b border-gray-800">
                      <th className="py-2 px-3">Ticker</th>
                      <th className="py-2 px-3">Name</th>
                      <th className="py-2 px-3">Qty</th>
                      <th className="py-2 px-3">Entry Price</th>
                      <th className="py-2 px-3">Entry Date</th>
                      <th className="py-2 px-3">Peak Price</th>
                      <th className="py-2 px-3">Score</th>
                      <th className="py-2 px-3">Cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {g.positions.map((p) => (
                      <tr
                        key={p.lot_id}
                        className="border-b border-gray-800/50 hover:bg-gray-800/30"
                      >
                        <td className="py-2 px-3">
                          <Link
                            to={`/stock/${p.ticker}`}
                            className="text-blue-400 hover:underline font-medium"
                          >
                            {p.ticker}
                          </Link>
                        </td>
                        <td className="py-2 px-3 text-gray-400 text-xs">
                          {names[p.ticker] ?? ""}
                        </td>
                        <td className="py-2 px-3">{p.quantity}</td>
                        <td className="py-2 px-3">
                          ¥{p.entry_price.toLocaleString()}
                        </td>
                        <td className="py-2 px-3">{p.entry_date}</td>
                        <td className="py-2 px-3">
                          ¥{p.peak_price.toLocaleString()}
                        </td>
                        <td className="py-2 px-3">
                          {p.entry_score.toFixed(1)}
                        </td>
                        <td className="py-2 px-3 text-gray-400">
                          ¥{(p.entry_price * p.quantity).toLocaleString()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useTickerNames } from "../hooks/useTickerNames";

export default function Dashboard() {
  const portfolio = useQuery({
    queryKey: ["portfolio"],
    queryFn: api.portfolio,
  });
  const signalDates = useQuery({
    queryKey: ["signal-dates"],
    queryFn: api.signalDates,
  });
  const names = useTickerNames();

  const groups = portfolio.data?.groups ?? [];
  const latestSignalDate = signalDates.data?.[0];

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Dashboard</h2>

      {/* Portfolio summary cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {groups.map((g) => {
          const invested = g.positions.reduce(
            (sum, p) => sum + p.entry_price * p.quantity,
            0,
          );
          const totalCapital = g.initial_capital;
          return (
            <div
              key={g.id}
              className="bg-gray-900 border border-gray-800 rounded-lg p-5"
            >
              <h3 className="text-sm text-gray-400 mb-1">{g.name}</h3>
              <div className="text-2xl font-bold text-blue-400">
                ¥{g.cash.toLocaleString()}
              </div>
              <div className="text-xs text-gray-500 mt-1">
                Cash / Initial ¥{totalCapital.toLocaleString()}
              </div>
              <div className="mt-3 flex gap-4 text-sm">
                <div>
                  <span className="text-gray-500">Positions:</span>{" "}
                  <span className="text-gray-200">
                    {g.positions.length}
                  </span>
                </div>
                <div>
                  <span className="text-gray-500">Invested:</span>{" "}
                  <span className="text-gray-200">
                    ¥{invested.toLocaleString()}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
          <h3 className="text-sm text-gray-400 mb-1">Latest Signal</h3>
          <div className="text-xl font-bold text-green-400">
            {latestSignalDate ?? "—"}
          </div>
          <div className="text-xs text-gray-500 mt-1">
            Last updated: {portfolio.data?.last_updated ?? "—"}
          </div>
        </div>
      </div>

      {/* Positions table */}
      {groups.map((g) => (
        <div key={g.id}>
          <h3 className="text-lg font-semibold mb-2">
            Positions — {g.name}
          </h3>
          {g.positions.length === 0 ? (
            <p className="text-gray-500 text-sm">No open positions</p>
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
                    <th className="py-2 px-3">Peak</th>
                    <th className="py-2 px-3">Score</th>
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
                          className="text-blue-400 hover:underline"
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
                      <td className="py-2 px-3">{p.entry_score.toFixed(1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}

      {/* Quick links */}
      <div className="flex gap-3 flex-wrap">
        <Link
          to="/production"
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm"
        >
          Run Production Daily
        </Link>
        <Link
          to="/evaluation"
          className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm"
        >
          Run Evaluation
        </Link>
        <Link
          to="/signals"
          className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm"
        >
          View Signals
        </Link>
      </div>
    </div>
  );
}

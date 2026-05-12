import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import PortfolioValueChart, {
  type PortfolioValueChartPoint,
  type PortfolioValueChartSeries,
} from "../components/PortfolioValueChart";
import { useTickerNames } from "../hooks/useTickerNames";

type PortfolioHistoryResponse = Awaited<ReturnType<typeof api.portfolioHistory>>;
type PortfolioHistoryPoint = PortfolioHistoryResponse["points"][number];

function formatCurrency(value: number): string {
  return `¥${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function formatSignedCurrency(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatCurrency(value)}`;
}

function formatSignedPercent(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

function formatIndexValue(value: number): string {
  return value.toFixed(1);
}

function buildSeriesData(
  points: PortfolioHistoryPoint[],
  selector: (point: PortfolioHistoryPoint) => number | null | undefined,
): PortfolioValueChartPoint[] {
  return points.flatMap((point) => {
    const value = selector(point);
    return value == null ? [] : [{ date: point.date, value }];
  });
}

export default function Dashboard() {
  const portfolio = useQuery({
    queryKey: ["portfolio"],
    queryFn: api.portfolio,
  });
  const portfolioHistory = useQuery({
    queryKey: ["portfolio-history"],
    queryFn: api.portfolioHistory,
  });
  const signalDates = useQuery({
    queryKey: ["signal-dates"],
    queryFn: api.signalDates,
  });
  const names = useTickerNames();

  const groups = portfolio.data?.groups ?? [];
  const latestSignalDate = signalDates.data?.[0];
  const portfolioHistoryPoints = portfolioHistory.data?.points ?? [];
  const totalCapital = groups.reduce((sum, group) => sum + group.total_capital, 0);
  const totalCurrentValue = groups.reduce((sum, group) => sum + group.current_value, 0);
  const totalPnl = groups.reduce((sum, group) => sum + group.total_pnl, 0);
  const totalPnlPct =
    totalCapital === 0 ? 0 : (totalPnl / totalCapital) * 100;
  const assetSeries: PortfolioValueChartSeries[] = [
    {
      id: "portfolio",
      label: "总资产",
      color: "#60a5fa",
      data: buildSeriesData(portfolioHistoryPoints, (point) => point.current_value),
      lineWidth: 3,
      lastValueVisible: true,
    },
    {
      id: "capital",
      label: "总资金基线",
      color: "rgba(148, 163, 184, 0.55)",
      data: buildSeriesData(portfolioHistoryPoints, (point) => point.total_capital),
      lineWidth: 2,
      crosshairMarkerVisible: false,
    },
    {
      id: "topix",
      label: "TOPIX 持有资产",
      color: "#34d399",
      data: buildSeriesData(portfolioHistoryPoints, (point) => point.topix_value),
      lineWidth: 2,
    },
    {
      id: "nikkei225",
      label: "日经225 持有资产 (1321)",
      color: "#f59e0b",
      data: buildSeriesData(portfolioHistoryPoints, (point) => point.nikkei225_value),
      lineWidth: 2,
    },
  ];
  const normalizedSeries: PortfolioValueChartSeries[] = [
    {
      id: "normalized-portfolio",
      label: "策略净表现",
      color: "#60a5fa",
      data: buildSeriesData(
        portfolioHistoryPoints,
        (point) => point.normalized_portfolio,
      ),
      lineWidth: 3,
      lastValueVisible: true,
    },
    {
      id: "normalized-topix",
      label: "TOPIX",
      color: "#34d399",
      data: buildSeriesData(
        portfolioHistoryPoints,
        (point) => point.normalized_topix,
      ),
      lineWidth: 2,
    },
    {
      id: "normalized-nikkei225",
      label: "日经225 (1321)",
      color: "#f59e0b",
      data: buildSeriesData(
        portfolioHistoryPoints,
        (point) => point.normalized_nikkei225,
      ),
      lineWidth: 2,
    },
  ];
  const visibleAssetSeries = assetSeries.filter((series) => series.data.length > 0);
  const visibleNormalizedSeries = normalizedSeries.filter(
    (series) => series.data.length > 0,
  );
  const missingBenchmarkLabels = [
    visibleAssetSeries.some((series) => series.id === "topix") ? null : "TOPIX",
    visibleAssetSeries.some((series) => series.id === "nikkei225")
      ? null
      : "日经225 (1321)",
  ].filter((label): label is string => label !== null);

  const renderPortfolioHistoryChart = (
    series: PortfolioValueChartSeries[],
    formatter: (value: number) => string,
    emptyMessage: string,
  ) => {
    if (portfolioHistory.isLoading) {
      return (
        <div className="flex h-[280px] items-center justify-center rounded-lg border border-dashed border-gray-800 text-sm text-gray-500">
          Loading chart...
        </div>
      );
    }
    if (portfolioHistory.isError) {
      return (
        <div className="flex h-[280px] flex-col items-center justify-center rounded-lg border border-dashed border-red-900/60 bg-red-950/20 px-4 text-center text-sm text-red-300">
          <div>Portfolio history failed to load.</div>
          <div className="mt-2 text-xs text-red-200/80">
            {portfolioHistory.error instanceof Error
              ? portfolioHistory.error.message
              : "Unknown API error"}
          </div>
        </div>
      );
    }
    if (portfolioHistoryPoints.length === 0) {
      return (
        <div className="flex h-[280px] items-center justify-center rounded-lg border border-dashed border-gray-800 text-sm text-gray-500">
          No portfolio history available.
        </div>
      );
    }
    return (
      <PortfolioValueChart
        series={series}
        valueFormatter={formatter}
        emptyMessage={emptyMessage}
      />
    );
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <h2 className="text-2xl font-bold">Dashboard</h2>
        <div className="inline-flex items-center gap-2 self-start rounded-full border border-emerald-900/60 bg-emerald-950/30 px-3 py-1 text-xs">
          <span className="text-gray-500">Latest Signal</span>
          <span className="font-semibold text-emerald-300">
            {latestSignalDate ?? "—"}
          </span>
        </div>
      </div>

      {/* Portfolio summary cards */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {groups.map((g) => {
          const pnlClassName =
            g.total_pnl >= 0 ? "text-green-400" : "text-red-400";
          return (
            <div
              key={g.id}
              className={`bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-4 ${
                groups.length === 1 ? "lg:col-span-2" : ""
              }`}
            >
              <h3 className="text-sm text-gray-400 mb-1">{g.name}</h3>
              <div>
                <div className="text-xs text-gray-500">总资金</div>
                <div className="text-2xl font-bold text-blue-400">
                  {formatCurrency(g.total_capital)}
                </div>
              </div>
              <div>
                <div className="text-xs text-gray-500">当前价值</div>
                <div className="text-xl font-semibold text-gray-100">
                  {formatCurrency(g.current_value)}
                </div>
              </div>
              <div>
                <div className="text-xs text-gray-500">当前总盈亏</div>
                <div className={`text-lg font-semibold ${pnlClassName}`}>
                  {formatSignedCurrency(g.total_pnl)}
                  <span className="ml-2 text-sm font-medium text-gray-400">
                    ({formatSignedPercent(g.total_pnl_pct)})
                  </span>
                </div>
              </div>
              <div className="text-xs text-gray-500">
                现金 {formatCurrency(g.cash)} / 持仓市值 {formatCurrency(g.holdings_value)}
              </div>
            </div>
          );
        })}
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-4">
        <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
          <div>
            <h3 className="text-sm text-gray-400">总资产对照图</h3>
            <div className="mt-1 text-xl font-semibold text-gray-100">
              {formatCurrency(totalCurrentValue)}
            </div>
            <div className={totalPnl >= 0 ? "text-sm text-green-400" : "text-sm text-red-400"}>
              {formatSignedCurrency(totalPnl)} ({formatSignedPercent(totalPnlPct)})
            </div>
          </div>
          <div className="text-xs text-gray-500">
            基线资本 {formatCurrency(totalCapital)}
          </div>
        </div>
        <div className="flex flex-wrap gap-3 text-xs text-gray-400">
          {visibleAssetSeries.map((series) => (
            <div key={series.id} className="inline-flex items-center gap-2">
              <span
                className="h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: series.color }}
              />
              <span>{series.label}</span>
            </div>
          ))}
        </div>
        {missingBenchmarkLabels.length > 0 ? (
          <div className="text-xs text-amber-300/80">
            Comparison data unavailable: {missingBenchmarkLabels.join(" / ")}
          </div>
        ) : null}
        {renderPortfolioHistoryChart(
          assetSeries,
          formatCurrency,
          "No asset comparison data available.",
        )}
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-4">
        <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
          <div>
            <h3 className="text-sm text-gray-400">归一化净表现图</h3>
            <div className="mt-1 text-xl font-semibold text-gray-100">
              起点 100.0
            </div>
            <div className="text-sm text-gray-500">
              剔除中途入金/出金影响，比较策略与 TOPIX / 日经225(1321) 的净表现
            </div>
          </div>
          <div className="text-xs text-gray-500">
            日经225 使用 1321 代理
          </div>
        </div>
        <div className="flex flex-wrap gap-3 text-xs text-gray-400">
          {visibleNormalizedSeries.map((series) => (
            <div key={series.id} className="inline-flex items-center gap-2">
              <span
                className="h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: series.color }}
              />
              <span>{series.label}</span>
            </div>
          ))}
        </div>
        {renderPortfolioHistoryChart(
          normalizedSeries,
          formatIndexValue,
          "No normalized benchmark data available.",
        )}
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

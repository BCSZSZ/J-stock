import { Fragment, useMemo, useState } from "react";
import { api } from "../api/client";

type SectorAttributionResponse = Awaited<ReturnType<typeof api.sectorAttribution>>;
type HeatmapPeriod = SectorAttributionResponse["heatmap_periods"][number];
type SectorAttributionSector = SectorAttributionResponse["sectors"][number];

interface SectorAttributionPanelProps {
  data: SectorAttributionResponse | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
}

interface SectorRow {
  sector: string;
  currentValue: number;
  pnlByKey: Record<string, number>;
}

interface DonutSegment {
  label: string;
  color: string;
  absValue: number;
  pnl: number;
  currentValue: number;
}

const PROFIT_COLORS = [
  "#34d399",
  "#10b981",
  "#6ee7b7",
  "#2dd4bf",
  "#4ade80",
  "#22c55e",
  "#5eead4",
  "#86efac",
];

const LOSS_COLORS = [
  "#f87171",
  "#ef4444",
  "#fb7185",
  "#f97316",
  "#dc2626",
  "#e11d48",
  "#fdba74",
  "#fca5a5",
];

function formatCurrency(value: number): string {
  return `¥${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function formatSignedCurrency(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}¥${Math.abs(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function formatCompactSignedCurrency(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  const absoluteValue = Math.abs(value);
  if (absoluteValue >= 1_000_000) {
    return `${sign}¥${(absoluteValue / 1_000_000).toFixed(1)}M`;
  }
  if (absoluteValue >= 1_000) {
    return `${sign}¥${(absoluteValue / 1_000).toFixed(1)}K`;
  }
  return `${sign}¥${absoluteValue.toFixed(0)}`;
}

function buildHeatColor(value: number, maxAbsoluteValue: number): string {
  if (maxAbsoluteValue <= 0 || value === 0) {
    return "rgba(31, 41, 55, 0.65)";
  }
  const intensity = Math.max(0.18, Math.abs(value) / maxAbsoluteValue);
  if (value > 0) {
    return `rgba(52, 211, 153, ${Math.min(0.85, intensity)})`;
  }
  return `rgba(248, 113, 113, ${Math.min(0.85, intensity)})`;
}

function SectorDonutChart({
  segments,
  totalPnl,
  periodLabel,
  title,
  shareLabel,
  emptyMessage,
}: {
  segments: DonutSegment[];
  totalPnl: number;
  periodLabel: string;
  title: string;
  shareLabel: string;
  emptyMessage: string;
}) {
  const totalAbsValue = segments.reduce((sum, segment) => sum + segment.absValue, 0);
  if (segments.length === 0 || totalAbsValue <= 0) {
    return (
      <div className="flex h-[280px] items-center justify-center rounded-lg border border-dashed border-gray-800 text-sm text-gray-500">
        {emptyMessage}
      </div>
    );
  }

  let currentOffset = 0;
  const gradientStops = segments.map((segment) => {
    const start = currentOffset;
    currentOffset += (segment.absValue / totalAbsValue) * 360;
    return `${segment.color} ${start}deg ${currentOffset}deg`;
  });

  return (
    <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)] lg:items-center">
      <div className="mx-auto relative h-[220px] w-[220px]">
        <div
          className="h-full w-full rounded-full border border-gray-800"
          style={{ backgroundImage: `conic-gradient(${gradientStops.join(", ")})` }}
        />
        <div className="absolute inset-8 flex flex-col items-center justify-center rounded-full border border-gray-800 bg-gray-950/95 px-4 text-center">
          <div className="text-xs text-gray-500">{periodLabel}</div>
          <div className={`mt-2 text-lg font-semibold ${totalPnl >= 0 ? "text-green-400" : "text-red-400"}`}>
            {formatSignedCurrency(totalPnl)}
          </div>
          <div className="mt-2 text-[11px] text-gray-400">{title}</div>
          <div className="mt-1 text-[11px] text-gray-500">{shareLabel}</div>
        </div>
      </div>
      <div className="space-y-2">
        {segments.map((segment) => {
          const share = (segment.absValue / totalAbsValue) * 100;
          return (
            <div key={segment.label} className="flex items-center gap-3 rounded-lg border border-gray-800 bg-gray-950/60 px-3 py-2">
              <span
                className="h-3 w-3 flex-none rounded-full"
                style={{ backgroundColor: segment.color }}
              />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-gray-100">{segment.label}</div>
                <div className="text-xs text-gray-500">当前市值 {formatCurrency(segment.currentValue)}</div>
              </div>
              <div className="text-right">
                <div className={`text-sm font-medium ${segment.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                  {formatSignedCurrency(segment.pnl)}
                </div>
                <div className="text-xs text-gray-500">{share.toFixed(1)}%</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SectorRankingBars({
  rows,
  periodLabel,
}: {
  rows: Array<{ sector: string; pnl: number }>;
  periodLabel: string;
}) {
  if (rows.length === 0) {
    return (
      <div className="flex h-[280px] items-center justify-center rounded-lg border border-dashed border-gray-800 text-sm text-gray-500">
        No ranking data available.
      </div>
    );
  }

  const maxAbsoluteValue = Math.max(...rows.map((row) => Math.abs(row.pnl)), 1);
  return (
    <div className="space-y-3">
      <div className="text-xs text-gray-500">{periodLabel} 业种盈亏排名</div>
      {rows.map((row) => {
        const widthPercent = (Math.abs(row.pnl) / maxAbsoluteValue) * 100;
        return (
          <div key={row.sector} className="space-y-1">
            <div className="flex items-center justify-between gap-3 text-sm">
              <div className="truncate text-gray-200">{row.sector}</div>
              <div className={row.pnl >= 0 ? "text-green-400" : "text-red-400"}>
                {formatSignedCurrency(row.pnl)}
              </div>
            </div>
            <div className="h-2 rounded-full bg-gray-950/80">
              <div
                className={`h-2 rounded-full ${row.pnl >= 0 ? "bg-emerald-400" : "bg-rose-400"}`}
                style={{ width: `${widthPercent}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function SectorHeatmap({
  periods,
  rows,
}: {
  periods: HeatmapPeriod[];
  rows: SectorRow[];
}) {
  if (rows.length === 0 || periods.length === 0) {
    return (
      <div className="flex h-[240px] items-center justify-center rounded-lg border border-dashed border-gray-800 text-sm text-gray-500">
        No heatmap data available.
      </div>
    );
  }

  const definedValues = rows.flatMap((row) =>
    periods.flatMap((period) => {
      const value = row.pnlByKey[period.key];
      return value === undefined ? [] : [Math.abs(value)];
    }),
  );
  const maxAbsoluteValue = Math.max(...definedValues, 1);

  return (
    <div className="overflow-x-auto">
      <div
        className="grid min-w-[720px] gap-2"
        style={{ gridTemplateColumns: `180px repeat(${periods.length}, minmax(88px, 1fr))` }}
      >
        <div className="px-3 py-2 text-xs uppercase tracking-wide text-gray-500">业种</div>
        {periods.map((period) => (
          <div key={period.key} className="px-3 py-2 text-center text-xs uppercase tracking-wide text-gray-500">
            {period.label}
          </div>
        ))}
        {rows.map((row) => (
          <Fragment key={row.sector}>
            <div className="truncate rounded-lg border border-gray-800 bg-gray-950/60 px-3 py-3 text-sm text-gray-200">
              {row.sector}
            </div>
            {periods.map((period) => {
              const value = row.pnlByKey[period.key];
              const hasData = value !== undefined;
              return (
                <div
                  key={`${row.sector}-${period.key}`}
                  className={`rounded-lg border border-gray-800 px-2 py-3 text-center text-xs font-medium ${
                    hasData ? "text-gray-100" : "bg-gray-950/30 text-gray-700"
                  }`}
                  style={hasData ? { backgroundColor: buildHeatColor(value, maxAbsoluteValue) } : undefined}
                  title={hasData ? `${row.sector} ${period.label}: ${formatSignedCurrency(value)}` : `${row.sector} ${period.label}: no data`}
                >
                  {hasData ? formatCompactSignedCurrency(value) : ""}
                </div>
              );
            })}
          </Fragment>
        ))}
      </div>
    </div>
  );
}

function buildDonutSegments(
  rows: Array<{ sector: string; currentValue: number; pnl: number }>,
  palette: string[],
): DonutSegment[] {
  const primaryRows = rows.slice(0, 6);
  const otherRows = rows.slice(6);
  const segments = primaryRows.map((row, index) => ({
    label: row.sector,
    color: palette[index % palette.length] ?? "#60a5fa",
    absValue: Math.abs(row.pnl),
    pnl: row.pnl,
    currentValue: row.currentValue,
  }));
  if (otherRows.length > 0) {
    segments.push({
      label: "Others",
      color: "#6b7280",
      absValue: otherRows.reduce((sum, row) => sum + Math.abs(row.pnl), 0),
      pnl: otherRows.reduce((sum, row) => sum + row.pnl, 0),
      currentValue: otherRows.reduce((sum, row) => sum + row.currentValue, 0),
    });
  }
  return segments.filter((segment) => segment.absValue > 0);
}

export default function SectorAttributionPanel({
  data,
  isLoading,
  isError,
  error,
}: SectorAttributionPanelProps) {
  const [selectedPeriodKey, setSelectedPeriodKey] = useState("YTD");
  const summaryPeriods = data?.summary_periods ?? [];
  const heatmapPeriods = data?.heatmap_periods ?? [];
  const resolvedSelectedPeriodKey = summaryPeriods.some((period) => period.key === selectedPeriodKey)
    ? selectedPeriodKey
    : (summaryPeriods.find((period) => period.key === "YTD")?.key ?? summaryPeriods[0]?.key ?? "");
  const selectedPeriod = summaryPeriods.find((period) => period.key === resolvedSelectedPeriodKey);

  const summaryRows = useMemo<SectorRow[]>(() => {
    return (data?.sectors ?? [])
      .map((sectorItem: SectorAttributionSector) => {
        const pnlByKey: Record<string, number> = {};
        for (const metric of sectorItem.summary_periods) {
          pnlByKey[metric.period_key] = metric.pnl;
        }
        return {
          sector: sectorItem.sector,
          currentValue: sectorItem.current_value,
          pnlByKey,
        };
      })
      .sort((left, right) => {
        const leftMagnitude = Math.max(...Object.values(left.pnlByKey).map((value) => Math.abs(value)), 0);
        const rightMagnitude = Math.max(...Object.values(right.pnlByKey).map((value) => Math.abs(value)), 0);
        return rightMagnitude - leftMagnitude;
      });
  }, [data]);

  const heatmapRows = useMemo<SectorRow[]>(() => {
    return (data?.sectors ?? [])
      .map((sectorItem: SectorAttributionSector) => {
        const pnlByKey: Record<string, number> = {};
        for (const metric of sectorItem.heatmap_periods) {
          pnlByKey[metric.period_key] = metric.pnl;
        }
        return {
          sector: sectorItem.sector,
          currentValue: sectorItem.current_value,
          pnlByKey,
        };
      })
      .filter((row) => Object.keys(row.pnlByKey).length > 0)
      .sort((left, right) => {
        const leftMagnitude = Math.max(...Object.values(left.pnlByKey).map((value) => Math.abs(value)), 0);
        const rightMagnitude = Math.max(...Object.values(right.pnlByKey).map((value) => Math.abs(value)), 0);
        return rightMagnitude - leftMagnitude;
      });
  }, [data]);

  const heatmapYearLabel = heatmapPeriods[0]?.start_date.slice(0, 4) ?? data?.as_of_date.slice(0, 4) ?? "";

  const selectedRows = useMemo(() => {
    return summaryRows
      .map((row) => ({
        sector: row.sector,
        currentValue: row.currentValue,
        pnl: row.pnlByKey[resolvedSelectedPeriodKey] ?? 0,
      }))
      .filter((row) => row.pnl !== 0)
      .sort((left, right) => Math.abs(right.pnl) - Math.abs(left.pnl));
  }, [resolvedSelectedPeriodKey, summaryRows]);

  const profitRows = useMemo(() => {
    return selectedRows.filter((row) => row.pnl > 0).sort((left, right) => right.pnl - left.pnl);
  }, [selectedRows]);

  const lossRows = useMemo(() => {
    return selectedRows.filter((row) => row.pnl < 0).sort((left, right) => left.pnl - right.pnl);
  }, [selectedRows]);

  const profitSegments = useMemo(
    () => buildDonutSegments(profitRows, PROFIT_COLORS),
    [profitRows],
  );
  const lossSegments = useMemo(
    () => buildDonutSegments(lossRows, LOSS_COLORS),
    [lossRows],
  );

  const totalProfit = profitRows.reduce((sum, row) => sum + row.pnl, 0);
  const totalLoss = lossRows.reduce((sum, row) => sum + row.pnl, 0);

  if (isLoading) {
    return (
      <div className="flex h-[480px] items-center justify-center rounded-lg border border-dashed border-gray-800 bg-gray-900 text-sm text-gray-500">
        Loading sector attribution...
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex min-h-[240px] flex-col items-center justify-center rounded-lg border border-dashed border-red-900/60 bg-red-950/20 px-4 text-center text-sm text-red-300">
        <div>Sector attribution failed to load.</div>
        <div className="mt-2 text-xs text-red-200/80">
          {error instanceof Error ? error.message : "Unknown API error"}
        </div>
      </div>
    );
  }

  if (!data || (summaryPeriods.length === 0 && heatmapPeriods.length === 0)) {
    return (
      <div className="flex min-h-[240px] items-center justify-center rounded-lg border border-dashed border-gray-800 bg-gray-900 text-sm text-gray-500">
        No sector attribution data available.
      </div>
    );
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-5">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <h3 className="text-sm text-gray-400">业种盈亏归因</h3>
          <div className="mt-1 text-xl font-semibold text-gray-100">
            截至 {data.as_of_date}
          </div>
          <div className="text-sm text-gray-500">
            期间盈亏口径：期末持仓市值 - 期初持仓市值 + 卖出额 - 买入额
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {summaryPeriods.map((period) => {
            const isActive = period.key === resolvedSelectedPeriodKey;
            return (
              <button
                key={period.key}
                type="button"
                onClick={() => setSelectedPeriodKey(period.key)}
                className={`rounded-full border px-3 py-1.5 text-xs transition ${
                  isActive
                    ? "border-blue-500 bg-blue-500/20 text-blue-200"
                    : "border-gray-700 bg-gray-950/60 text-gray-400 hover:border-gray-500 hover:text-gray-200"
                }`}
              >
                {period.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="rounded-lg border border-gray-800 bg-gray-950/40 p-4 space-y-3">
          <div>
            <div className="text-sm text-gray-300">盈利业种构成</div>
            <div className="text-xs text-gray-500">
              {selectedPeriod?.label} | {selectedPeriod?.start_date} to {selectedPeriod?.end_date}
            </div>
          </div>
          <SectorDonutChart
            segments={profitSegments}
            totalPnl={totalProfit}
            periodLabel={selectedPeriod?.label ?? "Selected"}
            title="盈利合计"
            shareLabel="按绝对盈利占比"
            emptyMessage="No profitable sectors in this period."
          />
        </div>

        <div className="rounded-lg border border-gray-800 bg-gray-950/40 p-4 space-y-3">
          <div>
            <div className="text-sm text-gray-300">亏损业种构成</div>
            <div className="text-xs text-gray-500">
              {selectedPeriod?.label} | {selectedPeriod?.start_date} to {selectedPeriod?.end_date}
            </div>
          </div>
          <SectorDonutChart
            segments={lossSegments}
            totalPnl={totalLoss}
            periodLabel={selectedPeriod?.label ?? "Selected"}
            title="亏损合计"
            shareLabel="按绝对亏损占比"
            emptyMessage="No losing sectors in this period."
          />
        </div>

        <div className="rounded-lg border border-gray-800 bg-gray-950/40 p-4">
          <SectorRankingBars
            rows={selectedRows.slice(0, 10)}
            periodLabel={selectedPeriod?.label ?? "Selected"}
          />
        </div>
      </div>

      <div className="rounded-lg border border-gray-800 bg-gray-950/40 p-4 space-y-3">
        <div>
          <div className="text-sm text-gray-300">{heatmapYearLabel} 业种 x 月份热力图</div>
          <div className="text-xs text-gray-500">固定显示 1-12 月；没有数据的月份留空白，只对有数据的月份着色。</div>
        </div>
        <SectorHeatmap periods={heatmapPeriods} rows={heatmapRows} />
      </div>
    </div>
  );
}
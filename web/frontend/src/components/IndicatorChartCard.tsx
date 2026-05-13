import { useEffect, useRef, useState } from "react";
import {
  createChart,
  IChartApi,
  LineData,
  LineStyle,
  Time,
} from "lightweight-charts";

type IndicatorRow = Record<string, unknown>;

interface IndicatorSeriesConfig {
  key: string;
  label: string;
  type: "line" | "histogram";
  color?: string;
  positiveColor?: string;
  negativeColor?: string;
  lineWidth?: 1 | 2 | 3 | 4;
  precision?: number;
}

interface IndicatorReferenceLineConfig {
  value: number;
  label?: string;
  color?: string;
  lineWidth?: 1 | 2 | 3 | 4;
  lineStyle?: LineStyle;
}

interface IndicatorChartCardProps {
  title: string;
  rows: IndicatorRow[];
  series: IndicatorSeriesConfig[];
  height?: number;
  referenceLines?: IndicatorReferenceLineConfig[];
}

interface LegendState {
  date: string;
  values: Record<string, number | null>;
}

function formatLegendValue(value: number | null | undefined, precision = 2): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "--";
  }
  return value.toFixed(precision);
}

function normalizeTimeKey(time: Time | undefined): string | null {
  if (!time) {
    return null;
  }
  if (typeof time === "string") {
    return time;
  }
  if (typeof time === "number") {
    return new Date(time * 1000).toISOString().slice(0, 10);
  }
  if (typeof time === "object" && "year" in time && "month" in time && "day" in time) {
    const year = String(time.year);
    const month = String(time.month).padStart(2, "0");
    const day = String(time.day).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }
  return null;
}

function coerceNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export default function IndicatorChartCard({
  title,
  rows,
  series,
  height = 180,
  referenceLines = [],
}: IndicatorChartCardProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<IChartApi | null>(null);
  const [legend, setLegend] = useState<LegendState | null>(null);

  useEffect(() => {
    if (!chartRef.current || rows.length === 0 || series.length === 0) {
      return;
    }

    const processedRows = rows
      .map((row) => {
        const dateValue = row.Date;
        if (typeof dateValue !== "string" || !dateValue) {
          return null;
        }

        const values: Record<string, number | null> = {};
        let hasValue = false;
        for (const item of series) {
          const nextValue = coerceNumber(row[item.key]);
          values[item.key] = nextValue;
          if (nextValue !== null) {
            hasValue = true;
          }
        }

        if (!hasValue) {
          return null;
        }

        return {
          time: dateValue,
          values,
        };
      })
      .filter((row): row is { time: string; values: Record<string, number | null> } => row !== null);

    if (processedRows.length === 0) {
      return;
    }

    const valuesByTime = new Map<string, Record<string, number | null>>();
    for (const row of processedRows) {
      valuesByTime.set(row.time, row.values);
    }

    const latestRow = processedRows[processedRows.length - 1]!;
    setLegend({ date: latestRow.time, values: latestRow.values });

    if (chartInstance.current) {
      chartInstance.current.remove();
      chartInstance.current = null;
    }

    const chart = createChart(chartRef.current, {
      width: chartRef.current.clientWidth,
      height,
      layout: {
        background: { color: "#0a0a0f" },
        textColor: "#9ca3af",
      },
      grid: {
        vertLines: { color: "#1f2937" },
        horzLines: { color: "#1f2937" },
      },
      crosshair: { mode: 0 },
      timeScale: {
        timeVisible: false,
      },
      handleScale: false,
      handleScroll: false,
      rightPriceScale: {
        borderColor: "#374151",
      },
    });
    chartInstance.current = chart;

    let referenceLinesApplied = false;

    for (const item of series) {
      const precision = item.precision ?? 2;
      if (item.type === "line") {
        const lineSeries = chart.addLineSeries({
          color: item.color ?? "#60a5fa",
          lineWidth: item.lineWidth ?? 2,
          priceLineVisible: false,
          lastValueVisible: true,
          priceFormat: {
            type: "price",
            precision,
            minMove: precision > 0 ? 1 / 10 ** precision : 1,
          },
        });
        const lineData: LineData<Time>[] = processedRows
          .map((row) => {
            const value = row.values[item.key];
            if (value === null) {
              return null;
            }
            return {
              time: row.time as Time,
              value,
            };
          })
          .filter((row): row is LineData<Time> => row !== null);
        lineSeries.setData(lineData);

        if (!referenceLinesApplied && referenceLines.length > 0) {
          for (const referenceLine of referenceLines) {
            lineSeries.createPriceLine({
              price: referenceLine.value,
              color: referenceLine.color ?? "#6b7280",
              lineWidth: referenceLine.lineWidth ?? 1,
              lineStyle: referenceLine.lineStyle ?? LineStyle.Dashed,
              axisLabelVisible: true,
              title: referenceLine.label ?? String(referenceLine.value),
            });
          }
          referenceLinesApplied = true;
        }
        continue;
      }

      const histogramSeries = chart.addHistogramSeries({
        priceLineVisible: false,
        lastValueVisible: true,
        priceFormat: {
          type: "price",
          precision,
          minMove: precision > 0 ? 1 / 10 ** precision : 1,
        },
      });
      const histogramData = processedRows
        .map((row) => {
          const value = row.values[item.key];
          if (typeof value !== "number") {
            return null;
          }
          return {
            time: row.time as Time,
            value,
            color:
              value >= 0
                ? item.positiveColor ?? "#22c55e80"
                : item.negativeColor ?? "#ef444480",
          };
        })
        .filter(
          (row): row is { time: Time; value: number; color: string } => row !== null,
        );
      histogramSeries.setData(histogramData);
    }

    chart.timeScale().fitContent();

    chart.subscribeCrosshairMove((param) => {
      const nextTime = normalizeTimeKey(param.time);
      if (!nextTime) {
        setLegend({ date: latestRow.time, values: latestRow.values });
        return;
      }

      const nextValues = valuesByTime.get(nextTime);
      if (!nextValues) {
        setLegend({ date: latestRow.time, values: latestRow.values });
        return;
      }

      setLegend({
        date: nextTime,
        values: nextValues,
      });
    });

    const handleResize = () => {
      if (chartRef.current) {
        chart.applyOptions({ width: chartRef.current.clientWidth });
      }
    };

    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartInstance.current = null;
    };
  }, [height, referenceLines, rows, series]);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <div className="mb-3 flex flex-wrap items-center gap-3 text-xs text-gray-400">
        <span className="font-semibold text-gray-200">{title}</span>
        {legend?.date ? <span>{legend.date}</span> : null}
        {series.map((item) => (
          <span key={item.key} className="inline-flex items-center gap-1">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{
                backgroundColor:
                  item.type === "histogram"
                    ? item.positiveColor ?? "#22c55e80"
                    : item.color ?? "#60a5fa",
              }}
            />
            <span>{item.label}</span>
            <span className="text-gray-200">
              {formatLegendValue(legend?.values[item.key], item.precision ?? 2)}
            </span>
          </span>
        ))}
      </div>
      <div ref={chartRef} />
    </div>
  );
}
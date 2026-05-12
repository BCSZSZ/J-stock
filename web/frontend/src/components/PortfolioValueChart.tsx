import { useEffect, useRef } from "react";
import { createChart, IChartApi, LineData, Time } from "lightweight-charts";

export interface PortfolioValueChartPoint {
  date: string;
  value: number;
}

export interface PortfolioValueChartSeries {
  id: string;
  label: string;
  color: string;
  data: PortfolioValueChartPoint[];
  lineWidth?: 1 | 2 | 3 | 4;
  lastValueVisible?: boolean;
  crosshairMarkerVisible?: boolean;
}

interface PortfolioValueChartProps {
  series: PortfolioValueChartSeries[];
  height?: number;
  valueFormatter?: (value: number) => string;
  emptyMessage?: string;
}

function defaultValueFormatter(value: number): string {
  return `¥${Math.round(value).toLocaleString()}`;
}

export default function PortfolioValueChart({
  series,
  height = 280,
  valueFormatter = defaultValueFormatter,
  emptyMessage = "No portfolio history available.",
}: PortfolioValueChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<IChartApi | null>(null);
  const activeSeries = series.filter((entry) => entry.data.length > 0);

  useEffect(() => {
    if (!chartRef.current || activeSeries.length === 0) {
      return undefined;
    }

    if (chartInstance.current) {
      chartInstance.current.remove();
      chartInstance.current = null;
    }

    const chart = createChart(chartRef.current, {
      width: chartRef.current.clientWidth,
      height,
      layout: {
        background: { color: "#111827" },
        textColor: "#9ca3af",
      },
      grid: {
        vertLines: { color: "#1f2937" },
        horzLines: { color: "#1f2937" },
      },
      crosshair: { mode: 0 },
      rightPriceScale: {
        borderColor: "#374151",
      },
      timeScale: {
        borderColor: "#374151",
        timeVisible: true,
        secondsVisible: false,
      },
      localization: {
        priceFormatter: valueFormatter,
      },
    });
    chartInstance.current = chart;

    for (const entry of activeSeries) {
      const lineSeries = chart.addLineSeries({
        color: entry.color,
        lineWidth: entry.lineWidth ?? 2,
        priceLineVisible: false,
        lastValueVisible: entry.lastValueVisible ?? false,
        crosshairMarkerVisible: entry.crosshairMarkerVisible ?? true,
      });
      const lineData: LineData<Time>[] = entry.data.map((point) => ({
        time: point.date as Time,
        value: point.value,
      }));
      lineSeries.setData(lineData);
    }

    chart.timeScale().fitContent();

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
  }, [activeSeries, height, valueFormatter]);

  if (activeSeries.length === 0) {
    return (
      <div className="flex h-[280px] items-center justify-center rounded-lg border border-dashed border-gray-800 text-sm text-gray-500">
        {emptyMessage}
      </div>
    );
  }

  return <div ref={chartRef} className="w-full" />;
}
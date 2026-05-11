import { useEffect, useRef } from "react";
import { createChart, IChartApi, LineData, Time } from "lightweight-charts";

export interface PortfolioValuePoint {
  date: string;
  current_value: number;
  total_capital: number;
}

interface PortfolioValueChartProps {
  points: PortfolioValuePoint[];
}

export default function PortfolioValueChart({ points }: PortfolioValueChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!chartRef.current || points.length === 0) {
      return undefined;
    }

    if (chartInstance.current) {
      chartInstance.current.remove();
      chartInstance.current = null;
    }

    const chart = createChart(chartRef.current, {
      width: chartRef.current.clientWidth,
      height: 280,
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
        priceFormatter: (value: number) =>
          `¥${Math.round(value).toLocaleString()}`,
      },
    });
    chartInstance.current = chart;

    const valueSeries = chart.addLineSeries({
      color: "#60a5fa",
      lineWidth: 3,
      priceLineVisible: false,
      lastValueVisible: true,
    });
    const valueData: LineData<Time>[] = points.map((point) => ({
      time: point.date as Time,
      value: point.current_value,
    }));
    valueSeries.setData(valueData);

    const baselineSeries = chart.addLineSeries({
      color: "rgba(148, 163, 184, 0.5)",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    const baselineData: LineData<Time>[] = points.map((point) => ({
      time: point.date as Time,
      value: point.total_capital,
    }));
    baselineSeries.setData(baselineData);

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
  }, [points]);

  if (points.length === 0) {
    return (
      <div className="flex h-[280px] items-center justify-center rounded-lg border border-dashed border-gray-800 text-sm text-gray-500">
        No portfolio history available.
      </div>
    );
  }

  return <div ref={chartRef} className="w-full" />;
}
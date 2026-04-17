import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { createChart, IChartApi, CandlestickData, HistogramData, LineData, Time } from "lightweight-charts";
import { api } from "../api/client";
import { useTickerNames } from "../hooks/useTickerNames";

function calcEMA(data: { time: string; close: number }[], period: number): LineData<Time>[] {
  const k = 2 / (period + 1);
  const result: LineData<Time>[] = [];
  let ema = 0;
  for (let i = 0; i < data.length; i++) {
    const d = data[i]!;
    if (i === 0) {
      ema = d.close;
    } else {
      ema = d.close * k + ema * (1 - k);
    }
    if (i >= period - 1) {
      result.push({ time: d.time as Time, value: ema });
    }
  }
  return result;
}

export default function StockDetail() {
  const { ticker } = useParams<{ ticker: string }>();
  const names = useTickerNames();
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<IChartApi | null>(null);
  const [showEMA, setShowEMA] = useState({ ema20: true, ema50: true, ema200: false });

  const chartData = useQuery({
    queryKey: ["chart", ticker],
    queryFn: () => api.chartData(ticker!, 250),
    enabled: !!ticker,
  });

  const features = useQuery({
    queryKey: ["features", ticker],
    queryFn: () => api.features(ticker!, 30),
    enabled: !!ticker,
  });

  // Render candlestick chart
  useEffect(() => {
    if (!chartRef.current || !chartData.data?.length) return;

    // Clean up previous chart
    if (chartInstance.current) {
      chartInstance.current.remove();
      chartInstance.current = null;
    }

    const chart = createChart(chartRef.current, {
      width: chartRef.current.clientWidth,
      height: 400,
      layout: {
        background: { color: "#0a0a0f" },
        textColor: "#9ca3af",
      },
      grid: {
        vertLines: { color: "#1f2937" },
        horzLines: { color: "#1f2937" },
      },
      crosshair: { mode: 0 },
      timeScale: { timeVisible: false },
    });
    chartInstance.current = chart;

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });

    const candles: CandlestickData<Time>[] = chartData.data.map((d) => ({
      time: d.time as Time,
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
    }));
    candleSeries.setData(candles);

    // Volume as histogram on separate area
    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    const volumes: HistogramData<Time>[] = chartData.data.map((d) => ({
      time: d.time as Time,
      value: d.volume ?? 0,
      color: d.close >= d.open ? "#22c55e40" : "#ef444440",
    }));
    volumeSeries.setData(volumes);

    // EMA overlays
    if (showEMA.ema20) {
      const ema20 = chart.addLineSeries({ color: "#f59e0b", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
      ema20.setData(calcEMA(chartData.data!, 20));
    }
    if (showEMA.ema50) {
      const ema50 = chart.addLineSeries({ color: "#3b82f6", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
      ema50.setData(calcEMA(chartData.data!, 50));
    }
    if (showEMA.ema200) {
      const ema200 = chart.addLineSeries({ color: "#a855f7", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
      ema200.setData(calcEMA(chartData.data!, 200));
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
  }, [chartData.data, showEMA]);

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">
        {ticker ?? "Stock"}{" "}
        <span className="text-gray-400 text-lg font-normal">
          {names[ticker ?? ""] ?? ""}
        </span>
      </h2>

      {/* Chart */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div className="flex gap-2 mb-3">
          {([
            { key: "ema20", label: "EMA 20", color: "text-amber-400" },
            { key: "ema50", label: "EMA 50", color: "text-blue-400" },
            { key: "ema200", label: "EMA 200", color: "text-purple-400" },
          ] as const).map(({ key, label, color }) => (
            <button
              key={key}
              onClick={() => setShowEMA((s) => ({ ...s, [key]: !s[key] }))}
              className={`px-2 py-1 text-xs rounded border ${
                showEMA[key]
                  ? `${color} border-gray-600 bg-gray-800`
                  : "text-gray-600 border-gray-800"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <div ref={chartRef} />
      </div>

      {/* Recent feature data */}
      {features.data && features.data.length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-400 mb-3">
            Recent Indicators (last {features.data.length} days)
          </h3>
          <div className="overflow-x-auto">
            <table className="text-xs w-full">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800">
                  {Object.keys(features.data[0] ?? {})
                    .slice(0, 15)
                    .map((k) => (
                      <th key={k} className="py-1 px-2 text-left">
                        {k}
                      </th>
                    ))}
                </tr>
              </thead>
              <tbody>
                {features.data.slice(-10).map((row, i) => (
                  <tr
                    key={i}
                    className="border-b border-gray-800/30 hover:bg-gray-800/20"
                  >
                    {Object.keys(row)
                      .slice(0, 15)
                      .map((k) => (
                        <td key={k} className="py-1 px-2 text-gray-400">
                          {typeof row[k] === "number"
                            ? (row[k] as number).toFixed(2)
                            : String(row[k] ?? "")}
                        </td>
                      ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

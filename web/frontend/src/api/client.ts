import type { SignalRecord } from "../signalSemantics";

const BASE = "/api";

export type TradeHistoryEvent = {
  date: string;
  group_id: string;
  ticker: string;
  action: string;
  quantity: number;
  price: number;
  status?: string;
  event_id?: string;
  position_effects?: Array<Record<string, unknown>>;
  reason?: string;
  entry_reason?: string;
  benchmark_status?: string;
  execution_open_price?: number | null;
  actual_vs_open_jpy?: number | null;
  actual_vs_open_pct?: number | null;
  slippage_pct?: number | null;
  slippage_bps?: number | null;
  slippage_direction?: string;
  [key: string]: unknown;
};

export type TradeHistorySummary = {
  total_trades: number;
  benchmarked_trades: number;
  missing_open_trades: number;
  capital_weighted_avg_slippage_pct_overall: number | null;
  capital_weighted_avg_slippage_pct_buy: number | null;
  capital_weighted_avg_slippage_pct_sell: number | null;
  avg_slippage_pct_overall: number | null;
  avg_slippage_pct_buy: number | null;
  avg_slippage_pct_sell: number | null;
  avg_abs_error_jpy: number | null;
  median_slippage_pct: number | null;
};

export type TradeHistoryResponse = {
  schema_version?: number;
  events: TradeHistoryEvent[];
  summary: TradeHistorySummary;
  [key: string]: unknown;
};

export type EntryAnalysisBucketMode =
  | "manual"
  | "sliding"
  | "fixed"
  | "quantile"
  | "categorical";

export type EntryAnalysisRuleRange = {
  label?: string | null;
  min?: number | null;
  max?: number | null;
};

export type EntryAnalysisRule = {
  feature: string;
  mode: EntryAnalysisBucketMode;
  label?: string | null;
  ranges?: EntryAnalysisRuleRange[];
  min?: number | null;
  max?: number | null;
  window?: number | null;
  step?: number | null;
  bin_width?: number | null;
  quantiles?: number | null;
  include_null?: boolean;
};

export type EntryAnalysisOptions = {
  entry_strategies: string[];
  indicator_columns: string[];
  derived_feature_columns: string[];
  bucket_modes: EntryAnalysisBucketMode[];
  label_modes: string[];
  preset_rules: string[];
  defaults: {
    entry_strategies: string[];
    universe_files: string[];
    horizons: number[];
    primary_horizon: number;
    label_mode: string;
    min_samples: number;
    include_joint: boolean;
    save_candidates: boolean;
    data_root: string;
    output_dir: string;
  };
};

export type EntryAnalysisRunRequest = {
  entry_strategies?: string[];
  universe_files?: string[];
  start?: string;
  end?: string;
  years?: number[];
  horizons: number[];
  primary_horizon: number;
  indicator_columns?: string[];
  rules?: EntryAnalysisRule[];
  preset_rules?: string;
  label_mode: string;
  min_samples: number;
  include_joint: boolean;
  save_candidates: boolean;
  limit?: number | null;
  data_root: string;
  output_dir?: string;
};

export type EntryAnalysisDatasetSummary = {
  id: string;
  dataset_id: string;
  generated_at: string;
  candidate_count: number;
  entry_strategies: string[];
  start_date: string;
  end_date: string;
  horizons: number[];
  label_mode: string;
  output_dir: string;
};

export type EntryAnalysisDatasetSchema = {
  id: string;
  manifest: Record<string, unknown>;
  feature_columns: string[];
  numeric_features: string[];
  categorical_features: string[];
  horizons: number[];
  candidate_count: number;
};

export type EntryAnalysisFeatureCondition = {
  feature: string;
  operator: "between" | ">=" | ">" | "<=" | "<" | "==" | "!=" | "is_null" | "not_null";
  min?: number | null;
  max?: number | null;
  value?: string | number | boolean | null;
};

export type EntryAnalysisAggregateRequest = {
  conditions: EntryAnalysisFeatureCondition[];
  logic: "all" | "any";
  horizons: number[];
  group_by?: string | null;
  min_samples: number;
};

export type EntryAnalysisAggregateResponse = {
  id: string;
  manifest: Record<string, unknown>;
  logic: "all" | "any";
  baseline: Record<string, unknown>;
  filtered: Record<string, unknown>;
  groups: Array<Record<string, unknown>>;
};

export type StockPoolOption = {
  id: string;
  label: string;
  monitor_list_file: string;
  sector_pool_file?: string | null;
  atr_ratio_min?: number | null;
  atr_ratio_max?: number | null;
  notes?: string | null;
  enabled: boolean;
  catalog_file?: string | null;
};

function withOutputDir(path: string, outputDir?: string): string {
  if (!outputDir) return path;
  const params = new URLSearchParams({ output_dir: outputDir });
  return `${path}?${params.toString()}`;
}

function encodeDatasetId(datasetId: string): string {
  return datasetId.split("/").map(encodeURIComponent).join("/");
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  // System
  health: () => request<{ status: string; version: string }>("/system/health"),
  config: () => request<Record<string, unknown>>("/system/config"),

  // State
  portfolio: () =>
    request<{
      groups: Array<{
        id: string;
        name: string;
        initial_capital: number;
        cash: number;
        net_cash_flow: number;
        total_capital: number;
        holdings_value: number;
        current_value: number;
        total_pnl: number;
        total_pnl_pct: number;
        positions: Array<{
          ticker: string;
          quantity: number;
          entry_price: number;
          entry_date: string;
          entry_score: number;
          peak_price: number;
          lot_id: string;
          current_price: number | null;
          current_value: number | null;
        }>;
      }>;
      last_updated: string;
    }>("/state/portfolio"),

  portfolioHistory: () =>
    request<{
      points: Array<{
        date: string;
        total_capital: number;
        current_value: number;
        total_pnl: number;
        total_pnl_pct: number;
        topix_value: number | null;
        nikkei225_value: number | null;
        normalized_portfolio: number | null;
        normalized_topix: number | null;
        normalized_nikkei225: number | null;
      }>;
    }>("/state/portfolio-history"),

  sectorAttribution: () =>
    request<{
      as_of_date: string;
      summary_periods: Array<{
        key: string;
        label: string;
        start_date: string;
        end_date: string;
      }>;
      heatmap_periods: Array<{
        key: string;
        label: string;
        start_date: string;
        end_date: string;
      }>;
      sectors: Array<{
        sector: string;
        current_value: number;
        summary_periods: Array<{
          period_key: string;
          pnl: number;
          start_value: number;
          end_value: number;
          buy_amount: number;
          sell_amount: number;
        }>;
        heatmap_periods: Array<{
          period_key: string;
          pnl: number;
          start_value: number;
          end_value: number;
          buy_amount: number;
          sell_amount: number;
        }>;
      }>;
    }>("/state/sector-attribution"),

  tradeHistory: () => request<TradeHistoryResponse>("/state/trade-history"),
  cashHistory: () => request<Record<string, unknown>>("/state/cash-history"),
  signalDates: () => request<string[]>("/state/signals"),
  signals: (date: string) =>
    request<SignalRecord[]>(`/state/signals/${date}`),
  reportDates: () => request<string[]>("/state/reports"),
  report: (date: string) =>
    request<{ date: string; content: string }>(`/state/reports/${date}`),

  // Data
  features: (ticker: string, days = 120) =>
    request<Array<Record<string, unknown>>>(
      `/data/features/${ticker}?days=${days}`,
    ),
  chartData: (ticker: string, days = 250) =>
    request<
      Array<{
        time: string;
        open: number;
        high: number;
        low: number;
        close: number;
        volume?: number;
      }>
    >(`/data/features/${ticker}/chart?days=${days}`),
  monitorList: () => request<string[]>("/data/monitor-list"),
  tickers: () => request<string[]>("/data/tickers"),
  tickerNames: () => request<Record<string, string>>("/data/ticker-names"),
  nextTradingDay: (after: string) =>
    request<{ date: string }>(`/data/next-trading-day?after=${after}`),

  // Production
  productionStatus: () =>
    request<{
      last_updated: string;
      groups: Array<{
        id: string;
        name: string;
        cash: number;
        position_count: number;
        tickers: string[];
      }>;
    }>("/production/status"),
  productionOptions: () =>
    request<{
      production: {
        monitor_list_file: string;
        sector_pool_file: string;
        stock_pool_catalog_file: string;
      };
      defaults: {
        pool_id: string;
      };
      stock_pools: StockPoolOption[];
    }>("/production/options"),

  // Evaluation
  evalOptions: () =>
    request<{
      commands: string[];
      entry_strategies: string[];
      exit_strategies: string[];
      ranking_strategies: string[];
      modes: string[];
      entry_filter_modes: string[];
      entry_filter_names: string[];
      overlay_modes: string[];
      buy_fill_modes: string[];
      entry_reference_modes: string[];
      capacity_regime_modes: string[];
      ranking_modes: string[];
      position_profiles: string[];
      production: {
        entry_strategy: string;
        exit_strategy: string;
        ranking_strategy: string;
        monitor_list_file: string;
        stock_pool_catalog_file: string;
        report_file_pattern: string;
      };
      stock_pools: StockPoolOption[];
      defaults: {
        command: string;
        mode: string;
        override_strategies: boolean;
        buy_fill_mode: string;
        buy_fill_modes?: string[];
        entry_reference_mode: string;
        entry_reference_modes?: string[];
        fill_buffer_enabled: boolean;
        fill_buffer_pct: number;
        entry_strategies: string[];
        exit_strategies: string[];
        ranking_mode: string;
        ranking_strategies: string[];
        entry_filter_mode: string;
        entry_filter_names: string[];
        enable_overlay: boolean;
        overlay_modes: string[];
        exit_confirm_days: number | null;
        capacity_regime_mode: string;
        output_dir: string;
        universe_files: string[];
        universe_pool_ids: string[];
        position_file: string;
        profile_names: string[];
        report_file: string;
        min_train_years: number;
      };
    }>("/evaluation/options"),
  evalReportContext: (reportFile: string) =>
    request<{
      report_file: string;
      entry_strategy: string;
      exit_strategy: string;
    }>(
      `/evaluation/report-context?${new URLSearchParams({ report_file: reportFile }).toString()}`,
    ),

  evalResults: (outputDir?: string) =>
    request<Array<{ name: string; type: string; size: string }>>(
      withOutputDir("/evaluation/results", outputDir),
    ),
  evalResult: (filename: string, outputDir?: string) =>
    request<Record<string, unknown>>(
      withOutputDir(`/evaluation/results/${filename}`, outputDir),
    ),

  // Entry Analysis
  entryAnalysisOptions: () =>
    request<EntryAnalysisOptions>("/entry-analysis/options"),
  entryAnalysisResults: (outputDir?: string) =>
    request<Array<{ name: string; type: string; size: string }>>(
      withOutputDir("/entry-analysis/results", outputDir),
    ),
  entryAnalysisResult: (filename: string, outputDir?: string) =>
    request<Record<string, unknown>>(
      withOutputDir(`/entry-analysis/results/${filename}`, outputDir),
    ),
  entryAnalysisDatasets: (outputDir?: string) =>
    request<EntryAnalysisDatasetSummary[]>(
      withOutputDir("/entry-analysis/datasets", outputDir),
    ),
  entryAnalysisDatasetSchema: (datasetId: string, outputDir?: string) =>
    request<EntryAnalysisDatasetSchema>(
      withOutputDir(`/entry-analysis/datasets/${encodeDatasetId(datasetId)}/schema`, outputDir),
    ),
  entryAnalysisAggregate: (
    datasetId: string,
    body: EntryAnalysisAggregateRequest,
    outputDir?: string,
  ) =>
    request<EntryAnalysisAggregateResponse>(
      withOutputDir(`/entry-analysis/datasets/${encodeDatasetId(datasetId)}/aggregate`, outputDir),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),

  // Strategies
  strategies: () =>
    request<{
      entry: Array<Record<string, unknown>>;
      exit: Array<Record<string, unknown>>;
    }>("/strategies"),
  strategy: (name: string, type = "entry") =>
    request<Record<string, unknown>>(`/strategies/${name}?type=${type}`),
};

/** Connect to an SSE endpoint and yield lines. */
export async function* streamSSE(
  path: string,
  body: Record<string, unknown>,
): AsyncGenerator<{ line?: string; done?: boolean; exit_code?: number }> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API ${res.status}`);
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop()!;
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        yield JSON.parse(line.slice(6));
      }
    }
  }
}

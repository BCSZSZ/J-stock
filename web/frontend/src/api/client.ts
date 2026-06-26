import type { SignalRecord } from "../signalSemantics";

const BASE = "/api";

export type MomentumExhaustionMode = "off" | "shadow" | "enforce";
export type IndustryFilterMode = "off" | "shadow" | "enforce";
export type EntrySignalAnalysisProfile = "legacy" | "priority15";

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

export type EntrySignalAnalysisOptions = {
  entry_strategies: string[];
  label_modes: string[];
  analysis_profiles: EntrySignalAnalysisProfile[];
  entry_filter_modes: string[];
  defaults: {
    entry_strategies: string[];
    universe_files: string[];
    analysis_profile: EntrySignalAnalysisProfile;
    horizons: number[];
    primary_horizon: number;
    primary_horizons?: number[];
    label_mode: string;
    ranking_strategy: string;
    entry_filter_mode: string;
    entry_filter_names: string[];
    position_sizing_mode: string;
    risk_per_trade_pct: number;
    atr_stop_multiple: number;
    atr_ratio_min: number | null;
    atr_ratio_max: number | null;
    tail_guard_enabled: boolean;
    tail_guard_max_rank: number;
    momentum_exhaustion_mode: MomentumExhaustionMode;
    momentum_exhaustion_max_score: number;
    momentum_exhaustion_threshold_method: "absolute";
    industry_filter_mode: IndustryFilterMode;
    max_buy_per_industry_per_day: number;
    max_total_positions_per_industry: number;
    industry_reference_file: string;
    target_pcts: number[];
    stop_pcts: number[];
    target_stop_horizons: number[];
    checkpoint_days: number[];
    cooldown_days: number[];
    late_entry_days: number[];
    cost_bps: number[];
    data_root: string;
    output_dir: string;
  };
};

export type EntrySignalAnalysisRunRequest = {
  entry_strategies?: string[];
  universe_files?: string[];
  start?: string;
  end?: string;
  years?: number[];
  analysis_profile?: EntrySignalAnalysisProfile;
  horizons: number[];
  primary_horizon: number;
  primary_horizons?: number[];
  label_mode: "signal_close" | "next_open";
  ranking_strategy?: string | null;
  entry_filter_mode: "auto" | "off" | "atr" | "single" | "grid";
  entry_filter_names?: string[];
  position_sizing_mode?: "fixed" | "atr" | null;
  risk_per_trade_pct?: number | null;
  atr_stop_multiple?: number | null;
  atr_ratio_min?: number | null;
  atr_ratio_max?: number | null;
  tail_guard_enabled?: boolean | null;
  tail_guard_max_rank?: number | null;
  momentum_exhaustion_mode?: MomentumExhaustionMode | null;
  momentum_exhaustion_max_score?: number | null;
  momentum_exhaustion_threshold_method?: "absolute";
  industry_filter_mode?: IndustryFilterMode | null;
  max_buy_per_industry_per_day?: number | null;
  max_total_positions_per_industry?: number | null;
  industry_reference_file?: string | null;
  target_pcts?: number[];
  stop_pcts?: number[];
  target_stop_horizons?: number[];
  checkpoint_days?: number[];
  cooldown_days?: number[];
  late_entry_days?: number[];
  cost_bps?: number[];
  limit?: number | null;
  data_root: string;
  output_dir?: string;
};

export type EntrySignalAnalysisDatasetSummary = {
  id: string;
  dataset_id: string;
  generated_at: string;
  candidate_count: number;
  selected_count: number;
  entry_strategies: string[];
  start_date: string;
  end_date: string;
  horizons: number[];
  analysis_profile?: EntrySignalAnalysisProfile;
  label_mode: string;
  ranking_strategy: string;
  output_dir: string;
};

export type EntrySignalAnalysisHorizonStats = {
  count?: number;
  wins?: number;
  losses?: number;
  flats?: number;
  win_rate?: number | null;
  avg_return_pct?: number | null;
  median_return_pct?: number | null;
  mean_minus_median_pct?: number | null;
  mean_gt_median?: boolean | null;
  avg_loss_pct?: number | null;
  p10_return_pct?: number | null;
  p25_return_pct?: number | null;
  p50_return_pct?: number | null;
  p75_return_pct?: number | null;
  p90_return_pct?: number | null;
  trimmed_mean_1pct_return_pct?: number | null;
  trimmed_mean_5pct_return_pct?: number | null;
  winsorized_mean_1pct_return_pct?: number | null;
  winsorized_mean_5pct_return_pct?: number | null;
  p01_return_pct?: number | null;
  p05_return_pct?: number | null;
  p95_return_pct?: number | null;
  p99_return_pct?: number | null;
  max_return_pct?: number | null;
  min_return_pct?: number | null;
  total_sum_return_pct?: number | null;
  top_1pct_sum_return_pct?: number | null;
  top_5pct_sum_return_pct?: number | null;
  bottom_1pct_sum_return_pct?: number | null;
  bottom_5pct_sum_return_pct?: number | null;
  top_1pct_contribution_ratio?: number | null;
  top_5pct_contribution_ratio?: number | null;
  bottom_1pct_contribution_ratio?: number | null;
  bottom_5pct_contribution_ratio?: number | null;
  net_without_top_1pct_return_pct?: number | null;
  net_without_top_5pct_return_pct?: number | null;
  net_without_bottom_1pct_return_pct?: number | null;
  net_without_bottom_5pct_return_pct?: number | null;
  avg_price_diff?: number | null;
  [key: string]: unknown;
};

export type EntrySignalAnalysisPrimaryValidationSlice = {
  group_key: string;
  group_label: string;
  stats: EntrySignalAnalysisHorizonStats;
  strength_min?: number | null;
  strength_max?: number | null;
};

export type EntrySignalAnalysisPrimaryStrategyTailRobustnessRanking = {
  rank: number;
  group_key: string;
  group_label: string;
  entry_strategy: string;
  entry_filter_name: string;
  stats: EntrySignalAnalysisHorizonStats;
  primary_score: number;
  secondary_score: number;
  trimmed_mean_5pct_rank: number;
  median_return_rank: number;
  top_5pct_contribution_rank: number;
  p10_rank: number;
  avg_loss_rank: number;
  count_rank: number;
  avg_return_rank: number;
};

export type EntrySignalAnalysisPrimaryHorizonValidation = {
  primary_horizon: number;
  primary_horizon_label: string;
  primary_return_column: string;
  signal_strength_metric?: string | null;
  signal_strength_bucket_method?: string | null;
  market_regime_source?: string | null;
  market_regime_status?: string | null;
  market_regime_definition?: string | null;
  overall: EntrySignalAnalysisHorizonStats;
  by_year: EntrySignalAnalysisPrimaryValidationSlice[];
  by_month: EntrySignalAnalysisPrimaryValidationSlice[];
  by_strategy?: EntrySignalAnalysisPrimaryValidationSlice[];
  by_strategy_bucket?: EntrySignalAnalysisPrimaryValidationSlice[];
  by_market_regime: EntrySignalAnalysisPrimaryValidationSlice[];
  by_entry_filter: EntrySignalAnalysisPrimaryValidationSlice[];
  by_signal_strength_bucket: EntrySignalAnalysisPrimaryValidationSlice[];
  by_strategy_risk?: Array<Record<string, unknown>>;
  by_strategy_tail_robustness?: EntrySignalAnalysisPrimaryStrategyTailRobustnessRanking[];
};

export type EntrySignalAnalysisTopDailyWindows = {
  primary_horizon: number;
  primary_horizon_label: string;
  sort_column: string;
  windows: Array<Record<string, unknown>>;
};

export type EntrySignalAnalysisRunSummary = {
  generated_at?: string;
  candidate_count?: number;
  selected_count?: number;
  trading_day_count?: number;
  strategy_count?: number;
  effective_entry_filter_mode?: string | null;
  effective_entry_filter_names?: string[];
  overall?: Record<string, unknown>;
  primary_horizon_validation?: EntrySignalAnalysisPrimaryHorizonValidation;
  primary_horizon_validations?: EntrySignalAnalysisPrimaryHorizonValidation[];
  per_strategy?: Array<Record<string, unknown>>;
  top_daily_windows?: Array<Record<string, unknown>>;
  top_daily_windows_by_horizon?: EntrySignalAnalysisTopDailyWindows[];
  [key: string]: unknown;
};

export type EntrySignalAnalysisDatasetDetail = {
  id: string;
  manifest: Record<string, unknown>;
  summary: EntrySignalAnalysisRunSummary;
};

export type EntryExitValidationOptions = {
  entry_strategies: string[];
  exit_strategies: string[];
  execution_modes: string[];
  signal_scopes: string[];
  entry_filter_modes: string[];
  defaults: {
    entry_strategies: string[];
    exit_strategies: string[];
    universe_files: string[];
    horizons: number[];
    primary_horizon: number;
    execution_mode: string;
    signal_scope: string;
    ranking_strategy: string;
    entry_filter_mode: string;
    entry_filter_names: string[];
    atr_ratio_min: number | null;
    atr_ratio_max: number | null;
    tail_guard_enabled: boolean;
    tail_guard_max_rank: number;
    momentum_exhaustion_mode: MomentumExhaustionMode;
    momentum_exhaustion_max_score: number;
    momentum_exhaustion_threshold_method: "absolute";
    industry_filter_mode: IndustryFilterMode;
    max_buy_per_industry_per_day: number;
    max_total_positions_per_industry: number;
    industry_reference_file: string;
    max_holding_trading_days: number;
    partial_exit_policy: string;
    min_samples: number;
    data_root: string;
    output_dir: string;
  };
};

export type EntryExitValidationRunRequest = {
  entry_strategies?: string[];
  exit_strategies?: string[];
  universe_files?: string[];
  start?: string;
  end?: string;
  years?: number[];
  horizons: number[];
  primary_horizon: number;
  execution_mode: "next_open" | "signal_close";
  signal_scope: "all" | "selected";
  ranking_strategy?: string | null;
  entry_filter_mode: "auto" | "off" | "atr" | "single" | "grid";
  entry_filter_names?: string[];
  atr_ratio_min?: number | null;
  atr_ratio_max?: number | null;
  tail_guard_enabled?: boolean | null;
  tail_guard_max_rank?: number | null;
  momentum_exhaustion_mode?: MomentumExhaustionMode | null;
  momentum_exhaustion_max_score?: number | null;
  momentum_exhaustion_threshold_method?: "absolute";
  industry_filter_mode?: IndustryFilterMode | null;
  max_buy_per_industry_per_day?: number | null;
  max_total_positions_per_industry?: number | null;
  industry_reference_file?: string | null;
  max_holding_trading_days: number;
  partial_exit_policy: "first_sell_full_exit";
  min_samples: number;
  limit?: number | null;
  data_root: string;
  output_dir?: string;
};

export type EntryExitValidationDatasetSummary = {
  id: string;
  dataset_id: string;
  generated_at: string;
  candidate_count: number;
  simulated_trade_count: number;
  entry_strategies: string[];
  exit_strategies: string[];
  start_date: string;
  end_date: string;
  horizons: number[];
  execution_mode: string;
  signal_scope: string;
  ranking_strategy: string;
  output_dir: string;
};

export type EntryExitValidationRunSummary = {
  generated_at?: string;
  candidate_count?: number;
  simulated_trade_count?: number;
  entry_strategy_count?: number;
  exit_strategy_count?: number;
  combination_count?: number;
  market_regime_status?: string;
  market_regime_definition?: string | null;
  artifacts?: Record<string, string>;
  top_robust_combinations?: Array<Record<string, unknown>>;
  top_risk_combinations?: Array<Record<string, unknown>>;
  warnings?: string[];
  [key: string]: unknown;
};

export type EntryExitValidationDatasetDetail = {
  id: string;
  manifest: Record<string, unknown>;
  summary: EntryExitValidationRunSummary;
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

export type InputTradeImportPreviewRow = {
  ticker: string;
  action: string;
  quantity: number;
  price: number | null;
  date: string;
  source: string;
  fill_count: number | null;
};

export type InputTradeImportPreviewResponse = {
  signal_date: string;
  trade_date: string;
  latest_csv_file: string | null;
  latest_csv_mtime: string | null;
  rows: InputTradeImportPreviewRow[];
  warnings: string[];
  matched_count: number;
  csv_only_count: number;
  signal_only_count: number;
  mode: string;
};

export type IntradayOrderPlanCandidateRow = {
  ticker: string;
  group_id: string;
  ticker_name: string | null;
  industry_name: string | null;
  suggested_quantity: number;
  default_entry_price: number | null;
  reference_price: number | null;
  atr_value: number | null;
  exit_strategy: string | null;
  r_multiple: number | null;
  trail_multiple: number | null;
  initial_stop_multiple: number | null;
  rank: number | null;
  rank_score: number | null;
  reason: string | null;
  can_plan: boolean;
  warnings: string[];
};

export type IntradayOrderPlanCandidatesResponse = {
  signal_date: string;
  trade_date: string;
  rows: IntradayOrderPlanCandidateRow[];
};

export type IntradayOrderPlanFill = {
  ticker: string;
  group_id: string;
  quantity: number;
  actual_entry_price: number;
  high_since_buy?: number | null;
};

export type IntradayOrderPlanPreviewRequest = {
  signal_date: string;
  fills: IntradayOrderPlanFill[];
};

export type IntradayOrderPlanRow = {
  ticker: string;
  group_id: string;
  ticker_name: string | null;
  industry_name: string | null;
  quantity: number;
  suggested_quantity: number;
  actual_entry_price: number;
  high_since_buy: number;
  reference_price: number | null;
  atr_value: number;
  exit_strategy: string;
  r_multiple: number;
  r_value: number;
  tp1_r: number;
  tp2_r: number;
  tp1_price: number;
  tp2_price: number;
  tp1_gain_pct: number;
  tp2_gain_pct: number;
  tp1_quantity: number;
  remaining_quantity_after_tp1: number;
  initial_stop_multiple: number;
  trail_multiple: number;
  initial_stop_price: number;
  dynamic_trail_price: number;
  stop_trigger_price: number;
  stop_limit_price: number;
  stop_loss_pct: number;
  stop_limit_loss_pct: number;
  stop_limit_atr_buffer: number;
  stop_limit_buffer_jpy: number;
  formula_basis: string;
  warnings: string[];
};

export type IntradayOrderPlanPreviewResponse = {
  signal_date: string;
  trade_date: string;
  rows: IntradayOrderPlanRow[];
  warnings: string[];
};

export type MvxExitFamily = "MVX" | "MVXW" | "MVXWL";

export type MvxExitStrategyResolveRequest = {
  family: MvxExitFamily;
  n_values: string;
  r_values: string;
  t_values: string;
  d_values: string;
  b_values: string;
  i_values?: string | null;
  max_combinations?: number;
};

export type MvxExitStrategyResolveResponse = {
  family: MvxExitFamily;
  parameters: Record<string, string[]>;
  generated_names: string[];
  already_registered: string[];
  newly_registered: string[];
  duplicate_count: number;
  combination_count: number;
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
        position_sizing_mode: string;
        risk_per_trade_pct: number;
        atr_stop_multiple: number;
        atr_ratio_min: number | null;
        atr_ratio_max: number | null;
        momentum_exhaustion_mode: MomentumExhaustionMode;
        momentum_exhaustion_max_score: number;
        momentum_exhaustion_threshold_method: "absolute";
        industry_filter_mode: IndustryFilterMode;
        max_buy_per_industry_per_day: number;
        max_total_positions_per_industry: number;
        industry_reference_file: string;
      };
      stock_pools: StockPoolOption[];
    }>("/production/options"),
  inputTradeImportPreview: (signalDate: string) =>
    request<InputTradeImportPreviewResponse>(
      `/production/input-trades/import-preview?${new URLSearchParams({ signal_date: signalDate }).toString()}`,
    ),
  intradayOrderPlanCandidates: (signalDate: string) =>
    request<IntradayOrderPlanCandidatesResponse>(
      `/production/intraday-order-plan/candidates?${new URLSearchParams({ signal_date: signalDate }).toString()}`,
    ),
  intradayOrderPlanPreview: (payload: IntradayOrderPlanPreviewRequest) =>
    request<IntradayOrderPlanPreviewResponse>(
      "/production/intraday-order-plan/preview",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),

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
        include_continuous: boolean;
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
        position_sizing_mode: string;
        risk_per_trade_pct: number;
        atr_stop_multiple: number;
        atr_ratio_min: number | null;
        atr_ratio_max: number | null;
        momentum_exhaustion_mode: MomentumExhaustionMode;
        momentum_exhaustion_max_score: number;
        momentum_exhaustion_threshold_method: "absolute";
        industry_filter_mode: IndustryFilterMode;
        max_buy_per_industry_per_day: number;
        max_total_positions_per_industry: number;
        industry_reference_file: string;
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
  entrySignalAnalysisOptions: () =>
    request<EntrySignalAnalysisOptions>("/entry-signal-analysis/options"),
  entrySignalAnalysisDatasets: (outputDir?: string) =>
    request<EntrySignalAnalysisDatasetSummary[]>(
      withOutputDir("/entry-signal-analysis/datasets", outputDir),
    ),
  entrySignalAnalysisDatasetSummary: (datasetId: string, outputDir?: string) =>
    request<EntrySignalAnalysisDatasetDetail>(
      withOutputDir(
        `/entry-signal-analysis/datasets/${encodeDatasetId(datasetId)}/summary`,
        outputDir,
      ),
    ),

  entryExitValidationOptions: () =>
    request<EntryExitValidationOptions>("/entry-exit-validation/options"),
  entryExitValidationDatasets: (outputDir?: string) =>
    request<EntryExitValidationDatasetSummary[]>(
      withOutputDir("/entry-exit-validation/datasets", outputDir),
    ),
  entryExitValidationDatasetSummary: (datasetId: string, outputDir?: string) =>
    request<EntryExitValidationDatasetDetail>(
      withOutputDir(
        `/entry-exit-validation/datasets/${encodeDatasetId(datasetId)}/summary`,
        outputDir,
      ),
    ),

  // Strategies
  strategies: () =>
    request<{
      entry: Array<Record<string, unknown>>;
      exit: Array<Record<string, unknown>>;
    }>("/strategies"),
  strategy: (name: string, type = "entry") =>
    request<Record<string, unknown>>(`/strategies/${name}?type=${type}`),
  resolveMvxExitStrategies: (body: MvxExitStrategyResolveRequest) =>
    request<MvxExitStrategyResolveResponse>("/strategies/exit/mvx-family/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
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

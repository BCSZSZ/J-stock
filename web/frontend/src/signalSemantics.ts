export interface SignalRecord {
  ticker: string;
  ticker_name?: string | null;
  signal_type: string;
  action: string;
  confidence?: number | null;
  score?: number | null;
  current_price?: number | null;
  close_price?: number | null;
  planned_price?: number | null;
  suggested_qty?: number | null;
  required_capital?: number | null;
  position_qty?: number | null;
  planned_sell_qty?: number | null;
  planned_sell_value?: number | null;
  strategy_name?: string | null;
  reason?: string | null;
  capacity_blocking_reason?: string | null;
  exit_trigger?: string | null;
  execution_intent?: string | null;
  execution_method?: string | null;
  execution_summary?: string | null;
  execution_period?: string | null;
  broker_order_type?: string | null;
  oco1_price?: number | null;
  oco1_condition?: string | null;
  oco2_trigger_price?: number | null;
  oco2_limit_price?: number | null;
  oco2_order_mode?: string | null;
  formula_basis?: string | null;
  guidance_notes?: string | null;
  momentum_rank?: number | null;
  momentum_value?: number | null;
  momentum_exhaustion_mode?: string | null;
  momentum_exhaustion_threshold_method?: string | null;
  momentum_exhaustion_max_score?: number | null;
  momentum_exhaustion_score?: number | null;
  momentum_exhaustion_threshold?: number | null;
  momentum_exhaustion_blocked?: boolean | null;
  momentum_exhaustion_filtered?: boolean | null;
  momentum_exhaustion_reason?: string | null;
  industry_name?: string | null;
  industry_filter_mode?: string | null;
  industry_filter_max_buy_per_day?: number | null;
  industry_filter_max_total_positions?: number | null;
  industry_filter_rank?: number | null;
  industry_existing_positions?: number | null;
  industry_total_positions_after_buy?: number | null;
  industry_filter_daily_cap_blocked?: boolean | null;
  industry_filter_total_position_blocked?: boolean | null;
  industry_filter_blocked?: boolean | null;
  industry_filter_filtered?: boolean | null;
  industry_filter_reason?: string | null;
  is_executable?: boolean | null;
  is_executable_buy?: boolean | null;
  is_executable_sell?: boolean | null;
  rank?: number | null;
  rank_score?: number | null;
  signal_metadata?: Record<string, unknown> | null;
  tp_preview_available?: boolean | null;
  tp_reference_price?: number | null;
  tp_assumed_entry_price?: number | null;
  tp_r_multiple?: number | null;
  tp_r_value?: number | null;
  tp1_price?: number | null;
  tp2_price?: number | null;
  tp1_gain_pct?: number | null;
  tp2_gain_pct?: number | null;
  tp_exit_strategy?: string | null;
}

export type SignalTone = "sell" | "buy" | "filteredBuy" | "neutral";

export interface TakeProfitPreview {
  referencePrice: number;
  assumedEntryPrice: number;
  percentBasisPrice: number;
  usesActualEntryPrice: boolean;
  tp1Price: number;
  tp2Price: number;
  tp1GainPct: number;
  tp2GainPct: number;
}

const BUY_BLOCK_REASON_MARKERS = [
  "Filtered:",
  "Capacity blocked:",
  "SuggestedQty=0:",
  "Skipped:",
  "Overlay blocked new entries",
];

function asNumber(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function cleanText(value: string | null | undefined): string | null {
  const text = value?.trim();
  return text ? text : null;
}

function extractBuyBlockReason(reason: string | null | undefined): string | null {
  const text = cleanText(reason);
  if (text === null) {
    return null;
  }

  const blockedParts = text
    .split(";")
    .map((part) => part.trim())
    .filter((part) =>
      BUY_BLOCK_REASON_MARKERS.some((marker) => part.startsWith(marker)),
    );

  return blockedParts.length > 0 ? blockedParts.join("; ") : null;
}

function formatOrderPrice(value: number | null): string | null {
  if (value === null) {
    return null;
  }
  return `¥${value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatTakeProfitPrice(value: number): string {
  return `¥${value.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  })}`;
}

export function formatTakeProfitPct(value: number): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

export function getTakeProfitPreview(
  signal: SignalRecord,
  actualEntryPrice?: number | null,
): TakeProfitPreview | null {
  if (!isBuySignal(signal)) {
    return null;
  }

  const referencePrice = asNumber(signal.tp_reference_price);
  const assumedEntryPrice = asNumber(signal.tp_assumed_entry_price);
  const tp1Price = asNumber(signal.tp1_price);
  const tp2Price = asNumber(signal.tp2_price);

  if (
    referencePrice === null ||
    assumedEntryPrice === null ||
    tp1Price === null ||
    tp2Price === null
  ) {
    return null;
  }

  const parsedActualEntryPrice = asNumber(actualEntryPrice);
  const percentBasisPrice =
    parsedActualEntryPrice !== null && parsedActualEntryPrice > 0
      ? parsedActualEntryPrice
      : assumedEntryPrice;

  return {
    referencePrice,
    assumedEntryPrice,
    percentBasisPrice,
    usesActualEntryPrice: parsedActualEntryPrice !== null && parsedActualEntryPrice > 0,
    tp1Price,
    tp2Price,
    tp1GainPct: ((tp1Price - percentBasisPrice) / percentBasisPrice) * 100,
    tp2GainPct: ((tp2Price - percentBasisPrice) / percentBasisPrice) * 100,
  };
}

export function isBuySignal(signal: SignalRecord): boolean {
  return signal.signal_type === "BUY";
}

export function isSellSignal(signal: SignalRecord): boolean {
  return signal.signal_type === "SELL";
}

export function getExecutableBuy(signal: SignalRecord): boolean {
  if (typeof signal.is_executable_buy === "boolean") {
    return signal.is_executable_buy;
  }
  return isBuySignal(signal) && Number(signal.suggested_qty ?? 0) > 0;
}

export function getFilteredBuy(signal: SignalRecord): boolean {
  return isBuySignal(signal) && !getExecutableBuy(signal);
}

export function getExecutableSell(signal: SignalRecord): boolean {
  if (typeof signal.is_executable_sell === "boolean") {
    return signal.is_executable_sell;
  }
  return isSellSignal(signal) && Number(signal.planned_sell_qty ?? 0) > 0;
}

export function getExecutableSignal(signal: SignalRecord): boolean {
  if (typeof signal.is_executable === "boolean") {
    return signal.is_executable;
  }
  return getExecutableBuy(signal) || getExecutableSell(signal);
}

export function getMomentumRank(signal: SignalRecord): number | null {
  const momentumRank = asNumber(signal.momentum_rank);
  if (momentumRank !== null) {
    return momentumRank;
  }
  return isBuySignal(signal) ? asNumber(signal.rank) : null;
}

export function getMomentumValue(signal: SignalRecord): number | null {
  const momentumValue = asNumber(signal.momentum_value);
  if (momentumValue !== null) {
    return momentumValue;
  }
  return isBuySignal(signal) ? asNumber(signal.rank_score) : null;
}

export function getExecutionQuantity(signal: SignalRecord): number {
  if (getExecutableSell(signal)) {
    return Number(signal.planned_sell_qty ?? 0);
  }
  if (getExecutableBuy(signal)) {
    return Number(signal.suggested_qty ?? 0);
  }
  return 0;
}

export function getNormalizedTradeAction(signal: SignalRecord): "BUY" | "SELL" | null {
  if (getExecutableSell(signal)) {
    return "SELL";
  }
  if (getExecutableBuy(signal)) {
    return "BUY";
  }
  return null;
}

export function getDisplayAction(signal: SignalRecord): string {
  return signal.action || signal.signal_type;
}

export function getBuyBlockReason(signal: SignalRecord): string {
  const industryReason = cleanText(signal.industry_filter_reason);
  if (industryReason !== null) {
    return industryReason;
  }

  const momentumReason = cleanText(signal.momentum_exhaustion_reason);
  if (momentumReason !== null) {
    return momentumReason;
  }

  const capacityReason = cleanText(signal.capacity_blocking_reason);
  if (capacityReason !== null) {
    return `Capacity blocked: ${capacityReason}`;
  }

  const extractedReason = extractBuyBlockReason(signal.reason);
  if (extractedReason !== null) {
    return extractedReason;
  }

  return cleanText(signal.reason) ?? "BUY signal is not executable";
}

export function getSignalTone(signal: SignalRecord): SignalTone {
  if (getExecutableSell(signal)) {
    return "sell";
  }
  if (getExecutableBuy(signal)) {
    return "buy";
  }
  if (getFilteredBuy(signal)) {
    return "filteredBuy";
  }
  return "neutral";
}

export function getExecutionLabel(signal: SignalRecord): string {
  if (getExecutableSell(signal)) {
    return `SELL ${getExecutionQuantity(signal)}股`;
  }
  if (getExecutableBuy(signal)) {
    return `BUY ${getExecutionQuantity(signal)}股`;
  }
  if (getFilteredBuy(signal)) {
    return "Filtered Buy";
  }
  if (isBuySignal(signal)) {
    return "Candidate Buy";
  }
  if (isSellSignal(signal)) {
    return "Sell Watch";
  }
  return "Watch";
}

export function getSellIntent(signal: SignalRecord): string {
  if (!isSellSignal(signal)) {
    return "—";
  }
  return signal.execution_intent || "—";
}

export function getSellOrderLabel(signal: SignalRecord): string {
  if (!isSellSignal(signal)) {
    return "—";
  }
  return signal.execution_method || signal.broker_order_type || "—";
}

export function getSellPlanLabel(signal: SignalRecord): string {
  if (!isSellSignal(signal)) {
    return "—";
  }

  const oco1Price = formatOrderPrice(asNumber(signal.oco1_price));
  if (oco1Price !== null) {
    return signal.oco1_condition
      ? `${oco1Price} + ${signal.oco1_condition}`
      : oco1Price;
  }

  return signal.execution_summary || "—";
}

export function getSellTriggerLabel(signal: SignalRecord): string {
  if (!isSellSignal(signal)) {
    return "—";
  }

  const oco2Price = formatOrderPrice(asNumber(signal.oco2_trigger_price));
  if (oco2Price !== null) {
    const oco2LimitPrice = formatOrderPrice(asNumber(signal.oco2_limit_price));
    return oco2LimitPrice ? `${oco2Price} -> ${oco2LimitPrice}` : oco2Price;
  }

  return signal.exit_trigger || "—";
}

export function getSellPeriodLabel(signal: SignalRecord): string {
  if (!isSellSignal(signal)) {
    return "—";
  }
  return signal.execution_period || "—";
}

export function compareSignalsForDisplay(left: SignalRecord, right: SignalRecord): number {
  const leftRankBucket = getDisplayPriorityBucket(left);
  const rightRankBucket = getDisplayPriorityBucket(right);
  if (leftRankBucket !== rightRankBucket) {
    return leftRankBucket - rightRankBucket;
  }

  const leftMomentumRank = getMomentumRank(left) ?? Number.MAX_SAFE_INTEGER;
  const rightMomentumRank = getMomentumRank(right) ?? Number.MAX_SAFE_INTEGER;
  if (leftMomentumRank !== rightMomentumRank) {
    return leftMomentumRank - rightMomentumRank;
  }

  const leftMomentumValue = getMomentumValue(left) ?? Number.NEGATIVE_INFINITY;
  const rightMomentumValue = getMomentumValue(right) ?? Number.NEGATIVE_INFINITY;
  if (leftMomentumValue !== rightMomentumValue) {
    return rightMomentumValue - leftMomentumValue;
  }

  return left.ticker.localeCompare(right.ticker);
}

function getDisplayPriorityBucket(signal: SignalRecord): number {
  if (getExecutableSell(signal)) {
    return 0;
  }
  if (getExecutableBuy(signal)) {
    return 1;
  }
  if (isBuySignal(signal)) {
    return 2;
  }
  if (isSellSignal(signal)) {
    return 3;
  }
  return 4;
}

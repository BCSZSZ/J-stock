export interface SignalRecord {
  ticker: string;
  ticker_name?: string | null;
  signal_type: string;
  action: string;
  confidence?: number | null;
  score?: number | null;
  current_price?: number | null;
  planned_price?: number | null;
  suggested_qty?: number | null;
  required_capital?: number | null;
  position_qty?: number | null;
  planned_sell_qty?: number | null;
  planned_sell_value?: number | null;
  strategy_name?: string | null;
  reason?: string | null;
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
  is_executable?: boolean | null;
  is_executable_buy?: boolean | null;
  is_executable_sell?: boolean | null;
  rank?: number | null;
  rank_score?: number | null;
}

function asNumber(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
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

export function getExecutionLabel(signal: SignalRecord): string {
  if (getExecutableSell(signal)) {
    return `SELL ${getExecutionQuantity(signal)}股`;
  }
  if (getExecutableBuy(signal)) {
    return `BUY ${getExecutionQuantity(signal)}股`;
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

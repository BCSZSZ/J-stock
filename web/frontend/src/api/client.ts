const BASE = "/api";

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
        positions: Array<{
          ticker: string;
          quantity: number;
          entry_price: number;
          entry_date: string;
          entry_score: number;
          peak_price: number;
          lot_id: string;
        }>;
      }>;
      last_updated: string;
    }>("/state/portfolio"),

  tradeHistory: () => request<Record<string, unknown>>("/state/trade-history"),
  cashHistory: () => request<Record<string, unknown>>("/state/cash-history"),
  signalDates: () => request<string[]>("/state/signals"),
  signals: (date: string) =>
    request<Array<Record<string, unknown>>>(`/state/signals/${date}`),
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

  // Evaluation
  evalOptions: () =>
    request<{
      entry_strategies: string[];
      exit_strategies: string[];
      ranking_strategies: string[];
      modes: string[];
      ranking_modes: string[];
    }>("/evaluation/options"),

  evalResults: () =>
    request<Array<{ name: string; type: string; size: string }>>(
      "/evaluation/results",
    ),
  evalResult: (filename: string) =>
    request<Record<string, unknown>>(`/evaluation/results/${filename}`),

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

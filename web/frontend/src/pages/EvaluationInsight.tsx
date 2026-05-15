import {
  type ChangeEvent,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
  useTransition,
} from "react";
import { Link } from "react-router-dom";
import Papa, { type ParseError } from "papaparse";
import { useTickerNames } from "../hooks/useTickerNames";

type SortKey =
  | "entryDate"
  | "exitDate"
  | "ticker"
  | "company"
  | "marketRegime"
  | "shares"
  | "entryPrice"
  | "exitPrice"
  | "holdingDays"
  | "returnPct"
  | "returnJpy"
  | "exitCategory";
type SortDir = "asc" | "desc";
type OutcomeFilter = "all" | "win" | "loss";
type ExitFilter = "all" | "full" | "partial";
type RawEvaluationTrade = Record<string, string>;

type EvaluationTradeRow = {
  id: string;
  period: number;
  marketRegime: string;
  ticker: string;
  entryDate: string;
  entryPrice: number;
  exitDate: string;
  exitPrice: number;
  exitReason: string;
  exitCategory: string;
  holdingDays: number;
  shares: number;
  returnPct: number;
  returnJpy: number;
  isFullExit: boolean;
  isPartialExit: boolean;
  entryStrategy: string;
  exitStrategy: string;
  buyFillMode: string;
  rankingStrategy: string;
};

const REQUIRED_COLUMNS = [
  "period",
  "ticker",
  "entry_date",
  "entry_price",
  "exit_date",
  "exit_price",
  "exit_reason",
  "holding_days",
  "shares",
  "return_pct",
  "return_jpy",
  "exit_is_full_exit",
  "exit_is_partial_exit",
] as const;

const collator = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: "base",
});

function parseNumber(value: string | undefined): number {
  const parsed = Number(value ?? "");
  return Number.isFinite(parsed) ? parsed : 0;
}

function parseBoolean(value: string | undefined): boolean {
  return String(value ?? "").toLowerCase() === "true";
}

function detectYear(row: RawEvaluationTrade): number {
  const period = Number.parseInt(row.period ?? "", 10);
  if (Number.isFinite(period)) {
    return period;
  }
  const entryYear = Number.parseInt((row.entry_date ?? "").slice(0, 4), 10);
  return Number.isFinite(entryYear) ? entryYear : 0;
}

function normalizeExitCategory(reason: string): string {
  if (reason.startsWith("TP2 hit")) return "TP2";
  if (reason.startsWith("TP1 hit")) return "TP1";
  if (reason.startsWith("Bias overheat")) return "BiasOverheat";
  if (reason.startsWith("R1 trailing stop")) return "R1_ATRTrailing";
  if (reason.startsWith("L2 histogram window decay")) return "L2_HistWindowDecay";
  if (reason.startsWith("Time stop")) return "TimeStop";
  return "Other";
}

function formatCurrency(value: number): string {
  return `¥${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function formatSignedCurrency(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatCurrency(value)}`;
}

function formatSignedPercent(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function parseTradesCsv(text: string): {
  trades: EvaluationTradeRow[];
  years: number[];
  warnings: string[];
} {
  const parsed = Papa.parse<RawEvaluationTrade>(text, {
    header: true,
    skipEmptyLines: "greedy",
  });

  const headers = parsed.meta.fields ?? [];
  const missingColumns = REQUIRED_COLUMNS.filter((column) => !headers.includes(column));
  if (missingColumns.length > 0) {
    throw new Error(`Missing required columns: ${missingColumns.join(", ")}`);
  }

  const warnings = parsed.errors.slice(0, 5).map((error: ParseError) => {
    const line = error.row == null ? "unknown" : error.row + 2;
    return `Line ${line}: ${error.message}`;
  });

  const trades = parsed.data.flatMap((row: RawEvaluationTrade, index: number) => {
    if (!row.ticker || !row.entry_date || !row.exit_date) {
      return [];
    }
    return [
      {
        id: `${row.period}-${row.ticker}-${row.entry_date}-${row.exit_date}-${index}`,
        period: detectYear(row),
        marketRegime: row.market_regime ?? "",
        ticker: String(row.ticker ?? ""),
        entryDate: row.entry_date ?? "",
        entryPrice: parseNumber(row.entry_price),
        exitDate: row.exit_date ?? "",
        exitPrice: parseNumber(row.exit_price),
        exitReason: row.exit_reason ?? "",
        exitCategory: normalizeExitCategory(row.exit_reason ?? ""),
        holdingDays: Math.max(0, Math.trunc(parseNumber(row.holding_days))),
        shares: Math.max(0, Math.trunc(parseNumber(row.shares))),
        returnPct: parseNumber(row.return_pct),
        returnJpy: parseNumber(row.return_jpy),
        isFullExit: parseBoolean(row.exit_is_full_exit),
        isPartialExit: parseBoolean(row.exit_is_partial_exit),
        entryStrategy: row.entry_strategy ?? "",
        exitStrategy: row.exit_strategy ?? "",
        buyFillMode: row.buy_fill_mode ?? "",
        rankingStrategy: row.ranking_strategy ?? "",
      },
    ];
  });

  const years = Array.from(
    new Set(trades.map((trade) => trade.period).filter((year): year is number => year > 0)),
  ).sort((left, right) => right - left);

  return { trades, years, warnings };
}

export default function EvaluationInsight() {
  const inputRef = useRef<HTMLInputElement>(null);
  const tickerNames = useTickerNames();
  const [isPending, startTransition] = useTransition();
  const [fileName, setFileName] = useState("");
  const [trades, setTrades] = useState<EvaluationTradeRow[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isParsing, setIsParsing] = useState(false);
  const [selectedYear, setSelectedYear] = useState<number | null>(null);
  const [searchText, setSearchText] = useState("");
  const deferredSearchText = useDeferredValue(searchText.trim().toLowerCase());
  const [outcomeFilter, setOutcomeFilter] = useState<OutcomeFilter>("all");
  const [exitFilter, setExitFilter] = useState<ExitFilter>("all");
  const [reasonFilter, setReasonFilter] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("exitDate");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const years = useMemo(
    () => [...new Set(trades.map((trade) => trade.period).filter((year) => year > 0))].sort((left, right) => right - left),
    [trades],
  );

  useEffect(() => {
    if (years.length === 0) {
      setSelectedYear(null);
      return;
    }
    if (selectedYear == null || !years.includes(selectedYear)) {
      setSelectedYear(years[0] ?? null);
    }
  }, [selectedYear, years]);

  const selectedYearIndex = selectedYear == null ? -1 : years.indexOf(selectedYear);
  const newerYear = selectedYearIndex > 0 ? (years[selectedYearIndex - 1] ?? null) : null;
  const olderYear =
    selectedYearIndex >= 0 && selectedYearIndex < years.length - 1
      ? (years[selectedYearIndex + 1] ?? null)
      : null;
  const yearTrades = useMemo(
    () => trades.filter((trade) => selectedYear == null || trade.period === selectedYear),
    [selectedYear, trades],
  );

  const reasonOptions = useMemo(
    () => [...new Set(yearTrades.map((trade) => trade.exitCategory))].sort(collator.compare),
    [yearTrades],
  );

  const summary = useMemo(() => {
    const tradeCount = yearTrades.length;
    const winCount = yearTrades.filter((trade) => trade.returnJpy > 0).length;
    const netReturnJpy = yearTrades.reduce((sum, trade) => sum + trade.returnJpy, 0);
    const avgHoldingDays =
      tradeCount === 0
        ? 0
        : yearTrades.reduce((sum, trade) => sum + trade.holdingDays, 0) / tradeCount;
    const partialExits = yearTrades.filter((trade) => trade.isPartialExit).length;

    return {
      tradeCount,
      winRate: tradeCount === 0 ? 0 : (winCount / tradeCount) * 100,
      netReturnJpy,
      avgHoldingDays,
      partialExits,
    };
  }, [yearTrades]);

  const filteredTrades = useMemo(() => {
    let filtered = yearTrades;

    if (deferredSearchText) {
      filtered = filtered.filter((trade) => {
        const name = String(tickerNames[trade.ticker] ?? "").toLowerCase();
        return [
          trade.ticker,
          name,
          trade.marketRegime,
          trade.exitReason,
          trade.entryStrategy,
          trade.exitStrategy,
          trade.buyFillMode,
          trade.rankingStrategy,
        ]
          .join(" ")
          .toLowerCase()
          .includes(deferredSearchText);
      });
    }

    if (outcomeFilter === "win") {
      filtered = filtered.filter((trade) => trade.returnJpy > 0);
    } else if (outcomeFilter === "loss") {
      filtered = filtered.filter((trade) => trade.returnJpy < 0);
    }

    if (exitFilter === "full") {
      filtered = filtered.filter((trade) => trade.isFullExit);
    } else if (exitFilter === "partial") {
      filtered = filtered.filter((trade) => trade.isPartialExit);
    }

    if (reasonFilter !== "all") {
      filtered = filtered.filter((trade) => trade.exitCategory === reasonFilter);
    }

    return [...filtered].sort((left, right) => {
      let comparison = 0;

      switch (sortKey) {
        case "entryDate":
          comparison = collator.compare(left.entryDate, right.entryDate);
          break;
        case "exitDate":
          comparison = collator.compare(left.exitDate, right.exitDate);
          break;
        case "ticker":
          comparison = collator.compare(left.ticker, right.ticker);
          break;
        case "company":
          comparison = collator.compare(
            String(tickerNames[left.ticker] ?? ""),
            String(tickerNames[right.ticker] ?? ""),
          );
          break;
        case "marketRegime":
          comparison = collator.compare(left.marketRegime, right.marketRegime);
          break;
        case "shares":
          comparison = left.shares - right.shares;
          break;
        case "entryPrice":
          comparison = left.entryPrice - right.entryPrice;
          break;
        case "exitPrice":
          comparison = left.exitPrice - right.exitPrice;
          break;
        case "holdingDays":
          comparison = left.holdingDays - right.holdingDays;
          break;
        case "returnPct":
          comparison = left.returnPct - right.returnPct;
          break;
        case "returnJpy":
          comparison = left.returnJpy - right.returnJpy;
          break;
        case "exitCategory":
          comparison = collator.compare(left.exitCategory, right.exitCategory);
          break;
      }

      return sortDir === "asc" ? comparison : -comparison;
    });
  }, [
    deferredSearchText,
    exitFilter,
    outcomeFilter,
    reasonFilter,
    sortDir,
    sortKey,
    tickerNames,
    yearTrades,
  ]);

  function sortIndicator(key: SortKey): string {
    if (sortKey !== key) {
      return "";
    }
    return sortDir === "asc" ? " ▲" : " ▼";
  }

  function toggleSort(key: SortKey): void {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
      return;
    }
    setSortKey(key);
    setSortDir(key === "exitDate" ? "desc" : "asc");
  }

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    setIsParsing(true);
    setError(null);

    try {
      const text = await file.text();
      const parsed = parseTradesCsv(text);
      startTransition(() => {
        setFileName(file.name);
        setTrades(parsed.trades);
        setWarnings(parsed.warnings);
        setSelectedYear(parsed.years[0] ?? null);
        setSearchText("");
        setOutcomeFilter("all");
        setExitFilter("all");
        setReasonFilter("all");
        setSortKey("exitDate");
        setSortDir("desc");
      });
    } catch (loadError) {
      const message = loadError instanceof Error ? loadError.message : "Failed to parse the selected CSV file.";
      setError(message);
      setTrades([]);
      setWarnings([]);
      setSelectedYear(null);
    } finally {
      setIsParsing(false);
      event.target.value = "";
    }
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h2 className="text-2xl font-bold">Evaluation Insight</h2>
        <p className="text-sm text-gray-400">
          Load an evaluation trades CSV, inspect it like a trade history page, and page through each year automatically.
        </p>
      </div>

      <section className="rounded-xl border border-gray-800 bg-gray-900 p-6 space-y-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="space-y-1">
            <h3 className="text-lg font-semibold">CSV Import</h3>
            <p className="text-sm text-gray-400">
              Choose an evaluation trades CSV from your local machine. Parsing happens locally in the browser.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <input
              ref={inputRef}
              type="file"
              accept=".csv,text/csv"
              className="hidden"
              onChange={handleFileChange}
            />
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="rounded-lg bg-blue-500 px-4 py-2 text-sm font-medium text-gray-950 transition hover:bg-blue-400"
            >
              {fileName ? "Choose another CSV" : "Choose CSV file"}
            </button>
            {fileName ? <span className="text-xs text-gray-500">{fileName}</span> : null}
          </div>
        </div>

        {!fileName ? (
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="flex w-full flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-gray-700 bg-gray-950/60 px-6 py-12 text-center transition hover:border-blue-400/60 hover:bg-gray-950"
          >
            <span className="text-base font-medium text-gray-200">Select an evaluation trades CSV</span>
            <span className="text-sm text-gray-500">
              Expected columns include period, ticker, entry_date, exit_date, return_pct, and return_jpy.
            </span>
          </button>
        ) : null}

        {isParsing || isPending ? <div className="text-sm text-blue-300">Parsing CSV...</div> : null}
        {error ? <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">{error}</div> : null}
        {warnings.length > 0 ? (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
            <div className="font-medium">Parsed with warnings</div>
            <ul className="mt-2 space-y-1 text-xs text-amber-100/80">
              {warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </section>

      {trades.length > 0 && selectedYear != null ? (
        <>
          <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
            <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
              <div className="text-xs uppercase tracking-wide text-gray-500">Loaded Trades</div>
              <div className="mt-2 text-2xl font-semibold">{summary.tradeCount.toLocaleString()}</div>
              <div className="mt-1 text-xs text-gray-500">{filteredTrades.length.toLocaleString()} shown after filters</div>
            </div>
            <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
              <div className="text-xs uppercase tracking-wide text-gray-500">Net P&amp;L</div>
              <div className={`mt-2 text-2xl font-semibold ${summary.netReturnJpy >= 0 ? "text-green-400" : "text-red-400"}`}>
                {formatSignedCurrency(summary.netReturnJpy)}
              </div>
              <div className="mt-1 text-xs text-gray-500">Current year page</div>
            </div>
            <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
              <div className="text-xs uppercase tracking-wide text-gray-500">Win Rate</div>
              <div className="mt-2 text-2xl font-semibold">{summary.winRate.toFixed(1)}%</div>
              <div className="mt-1 text-xs text-gray-500">Positive `return_jpy` rows</div>
            </div>
            <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
              <div className="text-xs uppercase tracking-wide text-gray-500">Avg Hold</div>
              <div className="mt-2 text-2xl font-semibold">{summary.avgHoldingDays.toFixed(2)}d</div>
              <div className="mt-1 text-xs text-gray-500">Based on `holding_days`</div>
            </div>
            <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
              <div className="text-xs uppercase tracking-wide text-gray-500">Partial Exits</div>
              <div className="mt-2 text-2xl font-semibold">{summary.partialExits.toLocaleString()}</div>
              <div className="mt-1 text-xs text-gray-500">Rows flagged as partial exits</div>
            </div>
          </section>

          <section className="rounded-xl border border-gray-800 bg-gray-900 p-4 space-y-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <div className="text-xs uppercase tracking-wide text-gray-500">Year Pagination</div>
                <div className="mt-1 text-lg font-semibold">{selectedYear}</div>
                <div className="text-xs text-gray-500">Page {selectedYearIndex + 1} of {years.length}</div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  disabled={newerYear == null}
                  onClick={() => setSelectedYear(newerYear)}
                  className="rounded-lg border border-gray-700 px-3 py-1.5 text-sm text-gray-300 transition hover:border-gray-500 hover:text-gray-100 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Newer
                </button>
                <button
                  type="button"
                  disabled={olderYear == null}
                  onClick={() => setSelectedYear(olderYear)}
                  className="rounded-lg border border-gray-700 px-3 py-1.5 text-sm text-gray-300 transition hover:border-gray-500 hover:text-gray-100 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Older
                </button>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {years.map((year) => (
                <button
                  key={year}
                  type="button"
                  onClick={() => setSelectedYear(year)}
                  className={`rounded-full px-3 py-1.5 text-sm transition ${
                    year === selectedYear
                      ? "bg-blue-500 text-gray-950"
                      : "border border-gray-700 text-gray-300 hover:border-gray-500 hover:text-gray-100"
                  }`}
                >
                  {year}
                </button>
              ))}
            </div>
          </section>

          <section className="rounded-xl border border-gray-800 bg-gray-900 p-4 space-y-4">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
              <input
                value={searchText}
                onChange={(event) => setSearchText(event.target.value)}
                placeholder="Search ticker, name, reason..."
                className="rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100 placeholder:text-gray-500"
              />
              <select
                value={outcomeFilter}
                onChange={(event) => setOutcomeFilter(event.target.value as OutcomeFilter)}
                className="rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100"
              >
                <option value="all">All outcomes</option>
                <option value="win">Wins only</option>
                <option value="loss">Losses only</option>
              </select>
              <select
                value={exitFilter}
                onChange={(event) => setExitFilter(event.target.value as ExitFilter)}
                className="rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100"
              >
                <option value="all">All exit types</option>
                <option value="full">Full exits</option>
                <option value="partial">Partial exits</option>
              </select>
              <select
                value={reasonFilter}
                onChange={(event) => setReasonFilter(event.target.value)}
                className="rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100"
              >
                <option value="all">All exit categories</option>
                {reasonOptions.map((reason) => (
                  <option key={reason} value={reason}>
                    {reason}
                  </option>
                ))}
              </select>
              <div className="flex items-center rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-500">
                {filteredTrades.length.toLocaleString()} / {summary.tradeCount.toLocaleString()} rows
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-800 text-left text-gray-500">
                    <th className="px-3 py-2 cursor-pointer select-none hover:text-gray-300" onClick={() => toggleSort("entryDate")}>Entry Date{sortIndicator("entryDate")}</th>
                    <th className="px-3 py-2 cursor-pointer select-none hover:text-gray-300" onClick={() => toggleSort("exitDate")}>Exit Date{sortIndicator("exitDate")}</th>
                    <th className="px-3 py-2 cursor-pointer select-none hover:text-gray-300" onClick={() => toggleSort("ticker")}>Ticker{sortIndicator("ticker")}</th>
                    <th className="px-3 py-2 cursor-pointer select-none hover:text-gray-300" onClick={() => toggleSort("company")}>Name{sortIndicator("company")}</th>
                    <th className="px-3 py-2 cursor-pointer select-none hover:text-gray-300" onClick={() => toggleSort("marketRegime")}>Regime{sortIndicator("marketRegime")}</th>
                    <th className="px-3 py-2 cursor-pointer select-none hover:text-gray-300" onClick={() => toggleSort("shares")}>Shares{sortIndicator("shares")}</th>
                    <th className="px-3 py-2 cursor-pointer select-none hover:text-gray-300" onClick={() => toggleSort("entryPrice")}>Entry{sortIndicator("entryPrice")}</th>
                    <th className="px-3 py-2 cursor-pointer select-none hover:text-gray-300" onClick={() => toggleSort("exitPrice")}>Exit{sortIndicator("exitPrice")}</th>
                    <th className="px-3 py-2 cursor-pointer select-none hover:text-gray-300" onClick={() => toggleSort("holdingDays")}>Hold{sortIndicator("holdingDays")}</th>
                    <th className="px-3 py-2 cursor-pointer select-none hover:text-gray-300" onClick={() => toggleSort("returnPct")}>Return %{sortIndicator("returnPct")}</th>
                    <th className="px-3 py-2 cursor-pointer select-none hover:text-gray-300" onClick={() => toggleSort("returnJpy")}>Return JPY{sortIndicator("returnJpy")}</th>
                    <th className="px-3 py-2 cursor-pointer select-none hover:text-gray-300" onClick={() => toggleSort("exitCategory")}>Exit Category{sortIndicator("exitCategory")}</th>
                    <th className="px-3 py-2">Exit Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredTrades.map((trade) => {
                    const companyName = String(tickerNames[trade.ticker] ?? "");
                    return (
                      <tr key={trade.id} className="border-b border-gray-800/60 hover:bg-gray-800/30">
                        <td className="px-3 py-2 text-gray-300">{trade.entryDate}</td>
                        <td className="px-3 py-2 text-gray-300">{trade.exitDate}</td>
                        <td className="px-3 py-2 font-medium">
                          <Link to={`/stock/${trade.ticker}`} className="text-blue-400 hover:underline">
                            {trade.ticker}
                          </Link>
                        </td>
                        <td className="px-3 py-2 text-xs text-gray-400">{companyName}</td>
                        <td className="px-3 py-2 text-xs text-gray-400 min-w-44">{trade.marketRegime}</td>
                        <td className="px-3 py-2">{trade.shares.toLocaleString()}</td>
                        <td className="px-3 py-2">{formatCurrency(trade.entryPrice)}</td>
                        <td className="px-3 py-2">{formatCurrency(trade.exitPrice)}</td>
                        <td className="px-3 py-2">{trade.holdingDays}d</td>
                        <td className={`px-3 py-2 ${trade.returnPct >= 0 ? "text-green-400" : "text-red-400"}`}>
                          {formatSignedPercent(trade.returnPct)}
                        </td>
                        <td className={`px-3 py-2 ${trade.returnJpy >= 0 ? "text-green-400" : "text-red-400"}`}>
                          {formatSignedCurrency(trade.returnJpy)}
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex flex-col gap-1">
                            <span className="text-xs font-medium text-gray-200">{trade.exitCategory}</span>
                            <span className={`text-[11px] ${trade.isPartialExit ? "text-amber-300" : "text-gray-500"}`}>
                              {trade.isPartialExit ? "Partial exit" : trade.isFullExit ? "Full exit" : "Mixed"}
                            </span>
                          </div>
                        </td>
                        <td className="px-3 py-2 text-xs text-gray-400 min-w-72">
                          <div>{trade.exitReason}</div>
                          <div className="mt-1 text-[11px] text-gray-500">
                            {trade.entryStrategy} → {trade.exitStrategy} · {trade.buyFillMode} · {trade.rankingStrategy}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
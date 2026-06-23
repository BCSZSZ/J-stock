import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  api,
  type IntradayOrderPlanCandidateRow,
  type IntradayOrderPlanFill,
  type IntradayOrderPlanPreviewResponse,
  type IntradayOrderPlanRow,
} from "../api/client";
import { useTickerNames } from "../hooks/useTickerNames";

type DraftByKey = Record<
  string,
  {
    quantity: string;
    actualEntryPrice: string;
    highSinceBuy: string;
  }
>;

function rowKey(row: { group_id: string; ticker: string }): string {
  return `${row.group_id}::${row.ticker}`;
}

function parsePositiveNumber(value: string): number | null {
  const parsed = Number(value.replace(/,/g, "").trim());
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function parsePositiveInt(value: string): number | null {
  const parsed = Number.parseInt(value.replace(/,/g, "").trim(), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function formatCurrency(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) {
    return "-";
  }
  return `¥${value.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  })}`;
}

function formatPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) {
    return "-";
  }
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) {
    return "-";
  }
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

function buildFills(
  rows: IntradayOrderPlanCandidateRow[],
  drafts: DraftByKey,
): IntradayOrderPlanFill[] {
  return rows.flatMap((row) => {
    if (!row.can_plan) {
      return [];
    }
    const draft = drafts[rowKey(row)];
    if (!draft) {
      return [];
    }
    const quantity =
      parsePositiveInt(draft.quantity) ?? row.suggested_quantity ?? null;
    const actualEntryPrice = parsePositiveNumber(draft.actualEntryPrice);
    if (quantity == null || actualEntryPrice == null) {
      return [];
    }
    return [
      {
        ticker: row.ticker,
        group_id: row.group_id,
        quantity,
        actual_entry_price: actualEntryPrice,
        high_since_buy: parsePositiveNumber(draft.highSinceBuy),
      },
    ];
  });
}

function PlanCells({ plan }: { plan: IntradayOrderPlanRow | undefined }) {
  if (!plan) {
    return (
      <>
        <td className="px-3 py-2 text-xs text-gray-600">-</td>
        <td className="px-3 py-2 text-xs text-gray-600">-</td>
        <td className="px-3 py-2 text-xs text-gray-600">-</td>
      </>
    );
  }

  return (
    <>
      <td className="px-3 py-2 text-xs">
        <div className="font-medium text-emerald-300">
          {formatCurrency(plan.tp1_price)}
        </div>
        <div className="text-gray-400">
          {plan.tp1_quantity}股 / {formatPercent(plan.tp1_gain_pct)}
        </div>
      </td>
      <td className="px-3 py-2 text-xs">
        <div className="font-medium text-emerald-200">
          {formatCurrency(plan.tp2_price)}
        </div>
        <div className="text-gray-400">
          残{plan.remaining_quantity_after_tp1}股 / 全{plan.quantity}股
        </div>
        <div className="text-gray-500">{formatPercent(plan.tp2_gain_pct)}</div>
      </td>
      <td className="px-3 py-2 text-xs">
        <div className="font-medium text-red-300">
          {formatCurrency(plan.stop_trigger_price)} {"->"}{" "}
          {formatCurrency(plan.stop_limit_price)}
        </div>
        <div className="text-gray-400">
          逆指値指値 / {formatPercent(plan.stop_loss_pct)}
        </div>
        <div className="text-gray-500">
          初期 {formatCurrency(plan.initial_stop_price)} | Trail{" "}
          {formatCurrency(plan.dynamic_trail_price)}
        </div>
      </td>
    </>
  );
}

export default function IntradayOrderPlan() {
  const signalDates = useQuery({
    queryKey: ["signal-dates"],
    queryFn: api.signalDates,
  });
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<DraftByKey>({});
  const [preview, setPreview] = useState<IntradayOrderPlanPreviewResponse | null>(
    null,
  );
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const names = useTickerNames();

  const effectiveDate = selectedDate ?? signalDates.data?.[0] ?? null;
  if (!selectedDate && signalDates.data?.[0]) {
    setSelectedDate(signalDates.data[0]);
  }

  const candidates = useQuery({
    queryKey: ["intraday-order-plan-candidates", effectiveDate],
    queryFn: () => api.intradayOrderPlanCandidates(effectiveDate!),
    enabled: !!effectiveDate,
  });

  useEffect(() => {
    if (!candidates.data) {
      return;
    }
    setDrafts((previous) => {
      const next: DraftByKey = {};
      for (const row of candidates.data.rows) {
        const key = rowKey(row);
        next[key] = previous[key] ?? {
          quantity: row.suggested_quantity > 0 ? String(row.suggested_quantity) : "",
          actualEntryPrice: "",
          highSinceBuy: "",
        };
      }
      return next;
    });
    setPreview(null);
    setPreviewError(null);
  }, [candidates.data]);

  const fills = useMemo(
    () => buildFills(candidates.data?.rows ?? [], drafts),
    [candidates.data?.rows, drafts],
  );
  const fillsKey = JSON.stringify(fills);

  useEffect(() => {
    if (!effectiveDate || fills.length === 0) {
      setPreview(null);
      setPreviewError(null);
      setPreviewLoading(false);
      return;
    }

    let cancelled = false;
    setPreviewLoading(true);
    const timer = window.setTimeout(() => {
      api
        .intradayOrderPlanPreview({
          signal_date: effectiveDate,
          fills,
        })
        .then((response) => {
          if (!cancelled) {
            setPreview(response);
            setPreviewError(null);
          }
        })
        .catch((error) => {
          if (!cancelled) {
            setPreview(null);
            setPreviewError(error instanceof Error ? error.message : String(error));
          }
        })
        .finally(() => {
          if (!cancelled) {
            setPreviewLoading(false);
          }
        });
    }, 300);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [effectiveDate, fillsKey]);

  const planByKey = useMemo(() => {
    const map = new Map<string, IntradayOrderPlanRow>();
    for (const row of preview?.rows ?? []) {
      map.set(rowKey(row), row);
    }
    return map;
  }, [preview]);

  function updateDraft(
    row: IntradayOrderPlanCandidateRow,
    field: keyof DraftByKey[string],
    value: string,
  ) {
    setDrafts((previous) => ({
      ...previous,
      [rowKey(row)]: {
        quantity:
          previous[rowKey(row)]?.quantity ??
          (row.suggested_quantity > 0 ? String(row.suggested_quantity) : ""),
        actualEntryPrice: previous[rowKey(row)]?.actualEntryPrice ?? "",
        highSinceBuy: previous[rowKey(row)]?.highSinceBuy ?? "",
        [field]: value,
      },
    }));
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold">Intraday Order Plan</h2>
          <div className="mt-1 flex flex-wrap gap-2 text-xs">
            <span className="rounded border border-gray-700 bg-gray-900 px-2 py-1 text-gray-300">
              Read-only
            </span>
            <span className="rounded border border-gray-700 bg-gray-900 px-2 py-1 text-gray-300">
              Actual fill basis
            </span>
            {candidates.data ? (
              <span className="rounded border border-gray-700 bg-gray-900 px-2 py-1 text-gray-300">
                Trade date {candidates.data.trade_date}
              </span>
            ) : null}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">Signal date</span>
          <select
            value={effectiveDate ?? ""}
            onChange={(event) => {
              setSelectedDate(event.target.value);
              setPreview(null);
              setPreviewError(null);
            }}
            className="h-9 rounded border border-gray-700 bg-gray-800 px-3 text-sm"
          >
            {(signalDates.data ?? []).map((date) => (
              <option key={date} value={date}>
                {date}
              </option>
            ))}
          </select>
        </div>
      </div>

      {candidates.isError ? (
        <div className="rounded border border-red-800 bg-red-950/40 px-4 py-3 text-sm text-red-200">
          Failed to load signal candidates: {String(candidates.error)}
        </div>
      ) : null}
      {previewError ? (
        <div className="rounded border border-red-800 bg-red-950/40 px-4 py-3 text-sm text-red-200">
          Failed to calculate order plan: {previewError}
        </div>
      ) : null}
      {(preview?.warnings ?? []).length > 0 ? (
        <div className="rounded border border-amber-800 bg-amber-950/30 px-4 py-3 text-sm text-amber-100">
          {preview?.warnings.join(" / ")}
        </div>
      ) : null}

      <div className="grid gap-3 md:grid-cols-4">
        <div className="rounded border border-gray-800 bg-gray-900 px-4 py-3">
          <div className="text-xs text-gray-500">BUY signals</div>
          <div className="mt-1 text-xl font-semibold">
            {candidates.data?.rows.length ?? 0}
          </div>
        </div>
        <div className="rounded border border-gray-800 bg-gray-900 px-4 py-3">
          <div className="text-xs text-gray-500">Planned rows</div>
          <div className="mt-1 text-xl font-semibold">{preview?.rows.length ?? 0}</div>
        </div>
        <div className="rounded border border-gray-800 bg-gray-900 px-4 py-3">
          <div className="text-xs text-gray-500">Valid fills</div>
          <div className="mt-1 text-xl font-semibold">{fills.length}</div>
        </div>
        <div className="rounded border border-gray-800 bg-gray-900 px-4 py-3">
          <div className="text-xs text-gray-500">Status</div>
          <div className="mt-1 text-sm font-medium text-gray-200">
            {previewLoading ? "Calculating" : fills.length > 0 ? "Ready" : "Waiting"}
          </div>
        </div>
      </div>

      <div className="overflow-x-auto rounded border border-gray-800">
        <table className="w-full min-w-[1500px] text-sm">
          <thead className="bg-gray-950/50">
            <tr className="border-b border-gray-800 text-left text-xs text-gray-500">
              <th className="px-3 py-2">Ticker</th>
              <th className="px-3 py-2">Signal</th>
              <th className="px-3 py-2">Params</th>
              <th className="px-3 py-2">Qty</th>
              <th className="px-3 py-2">Actual Buy</th>
              <th className="px-3 py-2">High</th>
              <th className="px-3 py-2">TP1</th>
              <th className="px-3 py-2">TP2</th>
              <th className="px-3 py-2">R1 / 逆指値</th>
              <th className="px-3 py-2">Reason</th>
            </tr>
          </thead>
          <tbody>
            {(candidates.data?.rows ?? []).map((row) => {
              const key = rowKey(row);
              const draft = drafts[key] ?? {
                quantity:
                  row.suggested_quantity > 0 ? String(row.suggested_quantity) : "",
                actualEntryPrice: "",
                highSinceBuy: "",
              };
              const plan = planByKey.get(key);
              return (
                <tr
                  key={key}
                  className="border-b border-gray-800/70 align-top hover:bg-gray-900/60"
                >
                  <td className="px-3 py-2">
                    <div className="font-medium text-blue-300">{row.ticker}</div>
                    <div className="max-w-[180px] truncate text-xs text-gray-400">
                      {names[row.ticker] ?? row.ticker_name ?? ""}
                    </div>
                    <div className="max-w-[180px] truncate text-xs text-gray-600">
                      {row.industry_name ?? "-"}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-xs">
                    <div className="text-gray-300">
                      #{row.rank ?? "-"} /{" "}
                      {row.rank_score == null
                        ? "-"
                        : `${row.rank_score >= 0 ? "+" : ""}${row.rank_score.toFixed(2)}`}
                    </div>
                    <div className="text-gray-500">
                      Ref {formatCurrency(row.reference_price)}
                    </div>
                    <div className="text-gray-500">
                      Default {formatCurrency(row.default_entry_price)}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-xs">
                    <div className="max-w-[230px] truncate text-gray-300">
                      {row.exit_strategy ?? "-"}
                    </div>
                    <div className="text-gray-500">
                      ATR {formatCurrency(row.atr_value)} | R{" "}
                      {formatNumber(row.r_multiple)} | T{" "}
                      {formatNumber(row.trail_multiple)} | I{" "}
                      {formatNumber(row.initial_stop_multiple)}
                    </div>
                    {!row.can_plan && row.warnings.length > 0 ? (
                      <div className="mt-1 text-amber-300">
                        {row.warnings.join(" / ")}
                      </div>
                    ) : null}
                  </td>
                  <td className="px-3 py-2">
                    <input
                      value={draft.quantity}
                      onChange={(event) =>
                        updateDraft(row, "quantity", event.target.value)
                      }
                      className="h-9 w-20 rounded border border-gray-700 bg-gray-800 px-2 text-right text-sm"
                      inputMode="numeric"
                    />
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <input
                        value={draft.actualEntryPrice}
                        onChange={(event) =>
                          updateDraft(row, "actualEntryPrice", event.target.value)
                        }
                        className="h-9 w-28 rounded border border-gray-700 bg-gray-800 px-2 text-right text-sm"
                        inputMode="decimal"
                        placeholder={formatNumber(row.default_entry_price)}
                      />
                      {row.default_entry_price ? (
                        <button
                          type="button"
                          onClick={() =>
                            updateDraft(
                              row,
                              "actualEntryPrice",
                              String(row.default_entry_price),
                            )
                          }
                          className="h-9 rounded border border-gray-700 px-2 text-xs text-gray-300 hover:bg-gray-800"
                        >
                          Ref
                        </button>
                      ) : null}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <input
                      value={draft.highSinceBuy}
                      onChange={(event) =>
                        updateDraft(row, "highSinceBuy", event.target.value)
                      }
                      className="h-9 w-28 rounded border border-gray-700 bg-gray-800 px-2 text-right text-sm"
                      inputMode="decimal"
                      placeholder={draft.actualEntryPrice || "optional"}
                    />
                  </td>
                  <PlanCells plan={plan} />
                  <td className="px-3 py-2 text-xs">
                    <div className="max-w-[260px] whitespace-normal break-words text-gray-500">
                      {row.reason ?? "-"}
                    </div>
                    {plan?.warnings.length ? (
                      <div className="mt-1 text-amber-300">
                        {plan.warnings.join(" / ")}
                      </div>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

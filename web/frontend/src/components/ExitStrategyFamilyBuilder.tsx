import { useEffect, useMemo, useState } from "react";
import {
  api,
  type MvxExitFamily,
  type MvxExitStrategyResolveResponse,
} from "../api/client";

type ExitStrategyFamilyBuilderProps = {
  selected: string[];
  onChange: (nextSelected: string[]) => void;
  defaultStrategy?: string;
  className?: string;
};

type ParsedMvxStrategy = {
  family: MvxExitFamily;
  n: string;
  r: string;
  t: string;
  d: string;
  b: string;
  i: string;
};

const FAMILY_OPTIONS: MvxExitFamily[] = ["MVX", "MVXW", "MVXWL"];

const DEFAULT_VALUES: ParsedMvxStrategy = {
  family: "MVXW",
  n: "5",
  r: "0.54",
  t: "1.3",
  d: "10",
  b: "20.0",
  i: "2.0",
};

const MVX_NAME_PATTERN = /^(MVXWL|MVXW|MVX)_N(\d+)_R([0-9]+(?:p[0-9]+)?)_T([0-9]+(?:p[0-9]+)?)_D(\d+)_B([0-9]+(?:p[0-9]+)?)(?:_I([0-9]+(?:p[0-9]+)?))?$/;

function tokenToInput(token: string | undefined, fallback: string): string {
  return token ? token.replace("p", ".") : fallback;
}

function parseMvxStrategyName(name: string | undefined): ParsedMvxStrategy | null {
  if (!name) {
    return null;
  }
  const match = MVX_NAME_PATTERN.exec(name.trim());
  if (!match) {
    return null;
  }
  const family = match[1] as MvxExitFamily;
  if (family === "MVXWL" && !match[7]) {
    return null;
  }
  return {
    family,
    n: match[2] ?? DEFAULT_VALUES.n,
    r: tokenToInput(match[3], DEFAULT_VALUES.r),
    t: tokenToInput(match[4], DEFAULT_VALUES.t),
    d: match[5] ?? DEFAULT_VALUES.d,
    b: tokenToInput(match[6], DEFAULT_VALUES.b),
    i: tokenToInput(match[7], DEFAULT_VALUES.i),
  };
}

function compactList(values: string[], limit = 8): string {
  if (values.length <= limit) {
    return values.join(", ");
  }
  return `${values.slice(0, limit).join(", ")} ... +${values.length - limit}`;
}

export default function ExitStrategyFamilyBuilder({
  selected,
  onChange,
  defaultStrategy,
  className = "",
}: ExitStrategyFamilyBuilderProps) {
  const [family, setFamily] = useState<MvxExitFamily>(DEFAULT_VALUES.family);
  const [nValues, setNValues] = useState(DEFAULT_VALUES.n);
  const [rValues, setRValues] = useState(DEFAULT_VALUES.r);
  const [tValues, setTValues] = useState(DEFAULT_VALUES.t);
  const [dValues, setDValues] = useState(DEFAULT_VALUES.d);
  const [bValues, setBValues] = useState(DEFAULT_VALUES.b);
  const [iValues, setIValues] = useState(DEFAULT_VALUES.i);
  const [initialized, setInitialized] = useState(false);
  const [resolving, setResolving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MvxExitStrategyResolveResponse | null>(null);

  useEffect(() => {
    if (initialized) {
      return;
    }
    const initialStrategy = selected[0] ?? defaultStrategy;
    if (!initialStrategy) {
      return;
    }
    const parsed = parseMvxStrategyName(initialStrategy);
    if (!parsed) {
      if (selected.length > 0) {
        onChange([]);
      }
      setInitialized(true);
      return;
    }
    setFamily(parsed.family);
    setNValues(parsed.n);
    setRValues(parsed.r);
    setTValues(parsed.t);
    setDValues(parsed.d);
    setBValues(parsed.b);
    setIValues(parsed.i);
    setInitialized(true);
  }, [defaultStrategy, initialized, onChange, selected]);

  const selectedPreview = useMemo(() => compactList(selected), [selected]);

  function updateFamily(nextFamily: MvxExitFamily) {
    setFamily(nextFamily);
    setResult(null);
    setError(null);
    if (nextFamily === "MVXWL" && !iValues.trim()) {
      setIValues(DEFAULT_VALUES.i);
    }
  }

  async function resolveStrategies() {
    setResolving(true);
    setError(null);
    try {
      const nextResult = await api.resolveMvxExitStrategies({
        family,
        n_values: nValues,
        r_values: rValues,
        t_values: tValues,
        d_values: dValues,
        b_values: bValues,
        i_values: family === "MVXWL" ? iValues : null,
        max_combinations: 200,
      });
      setResult(nextResult);
      onChange(nextResult.generated_names);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setResolving(false);
    }
  }

  const inputClass = "h-9 w-full rounded border border-gray-700 bg-gray-800 px-2 text-sm font-mono";
  const labelClass = "text-xs uppercase tracking-wide text-gray-500 block mb-1";

  return (
    <div className={`${className} min-h-[236px]`}>
      <div className="flex items-center justify-between gap-3 mb-2">
        <label className="text-xs uppercase tracking-wide text-gray-500">
          Exit Strategy Family
        </label>
        <span className="text-xs text-gray-400">{selected.length} selected</span>
      </div>

      <div className="grid grid-cols-3 gap-2 mb-3">
        {FAMILY_OPTIONS.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => updateFamily(option)}
            className={`h-9 rounded border px-2 text-sm font-medium transition-colors ${
              family === option
                ? "border-blue-500 bg-blue-600/20 text-blue-200"
                : "border-gray-700 bg-gray-800 text-gray-300 hover:bg-gray-700"
            }`}
          >
            {option}
          </button>
        ))}
      </div>

      <div className={`grid gap-2 ${family === "MVXWL" ? "grid-cols-2 xl:grid-cols-3" : "grid-cols-2 xl:grid-cols-5"}`}>
        <div>
          <label className={labelClass}>N</label>
          <input value={nValues} onChange={(event) => setNValues(event.target.value)} className={inputClass} />
        </div>
        <div>
          <label className={labelClass}>R</label>
          <input value={rValues} onChange={(event) => setRValues(event.target.value)} className={inputClass} />
        </div>
        <div>
          <label className={labelClass}>T</label>
          <input value={tValues} onChange={(event) => setTValues(event.target.value)} className={inputClass} />
        </div>
        <div>
          <label className={labelClass}>D</label>
          <input value={dValues} onChange={(event) => setDValues(event.target.value)} className={inputClass} />
        </div>
        <div>
          <label className={labelClass}>B</label>
          <input value={bValues} onChange={(event) => setBValues(event.target.value)} className={inputClass} />
        </div>
        {family === "MVXWL" && (
          <div>
            <label className={labelClass}>I</label>
            <input value={iValues} onChange={(event) => setIValues(event.target.value)} className={inputClass} />
          </div>
        )}
      </div>

      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          onClick={resolveStrategies}
          disabled={resolving}
          className="h-9 rounded bg-blue-600 px-3 text-sm font-medium text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-gray-700 disabled:text-gray-400"
        >
          {resolving ? "Resolving" : "Resolve"}
        </button>
        {result && (
          <span className="text-xs text-gray-400">
            {result.generated_names.length} generated, {result.newly_registered.length} new
          </span>
        )}
      </div>

      {error && <p className="mt-2 text-xs text-red-300 break-words">{error}</p>}

      <div className="mt-3 min-h-[40px] rounded border border-gray-800 bg-gray-950/40 px-2 py-2 text-xs text-gray-300">
        {selected.length > 0 ? selectedPreview : "No exit strategies selected."}
      </div>
    </div>
  );
}

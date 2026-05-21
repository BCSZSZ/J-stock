import { useDeferredValue, useMemo, useState } from "react";

type SortMode = "name-asc" | "selected-first" | "name-desc";
type ScopeMode = "all" | "selected" | "unselected";

type StrategyMultiSelectProps = {
  label?: string;
  options: string[];
  selected: string[];
  onToggle?: (name: string) => void;
  onChange?: (nextSelected: string[]) => void;
  emptyText?: string;
  searchPlaceholder?: string;
};

type StrategyGroup = {
  family: string;
  options: string[];
  selectedCount: number;
};

const NAME_COLLATOR = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: "base",
});

const FAMILY_SUFFIX_PATTERNS = [
  /StrictFresh$/,
  /MaxBiasPct\d+$/,
  /FollowExitBias$/,
  /Ret\d+[A-Za-z0-9]*$/,
  /MinHistDeltaNorm\d+$/,
  /LiteCombo$/,
  /ShockOverheatFilterV\d+$/,
  /ShockFilterV\d+$/,
  /FollowThroughFilterV\d+$/,
  /FragileBelowZeroLowADXFilterV\d+$/,
  /FragileBelowZeroFilterV\d+$/,
  /FragileBelowZeroDownweightV\d+$/,
  /BiasFilterV\d+$/,
  /_V\d+$/,
];

function sortOptions(
  options: string[],
  selectedSet: Set<string>,
  sortMode: SortMode,
) {
  const next = [...options];

  next.sort((left, right) => {
    if (sortMode === "selected-first") {
      const leftSelected = selectedSet.has(left) ? 1 : 0;
      const rightSelected = selectedSet.has(right) ? 1 : 0;

      if (leftSelected !== rightSelected) {
        return rightSelected - leftSelected;
      }
    }

    const direction = sortMode === "name-desc" ? -1 : 1;
    return NAME_COLLATOR.compare(left, right) * direction;
  });

  return next;
}

function parseBulkValues(raw: string) {
  return raw
    .split(/[\s,;]+/)
    .map((value) => value.trim())
    .filter(Boolean);
}

function deriveStrategyFamily(name: string) {
  if (!name) {
    return "Other";
  }

  if (name.includes("_")) {
    const [prefix] = name.split("_");
    return prefix || name;
  }

  let family = name.replace(/(Entry|Exit)([A-Z])$/, "$1");
  family = family.replace(/(Entry|Exit|Strategy)$/, "");

  let previous = "";
  while (family && family !== previous) {
    previous = family;
    for (const pattern of FAMILY_SUFFIX_PATTERNS) {
      family = family.replace(pattern, "");
    }
  }

  return family || name;
}

function StrategyMultiSelect({
  label,
  options,
  selected,
  onToggle,
  onChange,
  emptyText = "No strategies found.",
  searchPlaceholder = "Filter strategies...",
}: StrategyMultiSelectProps) {
  const [query, setQuery] = useState("");
  const [scopeMode, setScopeMode] = useState<ScopeMode>("all");
  const [sortMode, setSortMode] = useState<SortMode>("selected-first");
  const [bulkInput, setBulkInput] = useState("");
  const [bulkFeedback, setBulkFeedback] = useState<string | null>(null);
  const [expandedFamilies, setExpandedFamilies] = useState<Record<string, boolean>>({});
  const deferredQuery = useDeferredValue(query);

  const optionSet = useMemo(() => new Set(options), [options]);
  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const normalizedQuery = deferredQuery.trim().toLowerCase();

  const visibleGroups = useMemo(() => {
    const filtered = options.filter((option) => {
      const isSelected = selectedSet.has(option);

      if (scopeMode === "selected" && !isSelected) {
        return false;
      }

      if (scopeMode === "unselected" && isSelected) {
        return false;
      }

      if (!normalizedQuery) {
        return true;
      }

      return option.toLowerCase().includes(normalizedQuery);
    });

    const groups = new Map<string, string[]>();
    for (const option of filtered) {
      const family = deriveStrategyFamily(option);
      const bucket = groups.get(family);
      if (bucket) {
        bucket.push(option);
      } else {
        groups.set(family, [option]);
      }
    }

    const nextGroups: StrategyGroup[] = Array.from(groups.entries()).map(
      ([family, familyOptions]) => ({
        family,
        options: sortOptions(familyOptions, selectedSet, sortMode),
        selectedCount: familyOptions.filter((option) => selectedSet.has(option)).length,
      }),
    );

    nextGroups.sort((left, right) => {
      if (sortMode === "selected-first") {
        const leftSelected = left.selectedCount > 0 ? 1 : 0;
        const rightSelected = right.selectedCount > 0 ? 1 : 0;

        if (leftSelected !== rightSelected) {
          return rightSelected - leftSelected;
        }

        if (left.selectedCount !== right.selectedCount) {
          return right.selectedCount - left.selectedCount;
        }
      }

      const direction = sortMode === "name-desc" ? -1 : 1;
      return NAME_COLLATOR.compare(left.family, right.family) * direction;
    });

    return nextGroups;
  }, [normalizedQuery, options, scopeMode, selectedSet, sortMode]);

  const visibleCount = useMemo(
    () => visibleGroups.reduce((total, group) => total + group.options.length, 0),
    [visibleGroups],
  );

  const selectedSorted = useMemo(
    () => sortOptions(selected, selectedSet, "name-asc"),
    [selected, selectedSet],
  );

  function applySelection(nextSelected: string[]) {
    const deduped = Array.from(new Set(nextSelected));

    if (onChange) {
      onChange(deduped);
      return;
    }

    if (!onToggle) {
      return;
    }

    const nextSelectedSet = new Set(deduped);
    const touchedOptions = new Set([...selected, ...deduped]);

    for (const option of touchedOptions) {
      const isSelected = selectedSet.has(option);
      const shouldSelect = nextSelectedSet.has(option);

      if (isSelected !== shouldSelect) {
        onToggle(option);
      }
    }
  }

  function toggleOption(option: string) {
    applySelection(
      selectedSet.has(option)
        ? selected.filter((item) => item !== option)
        : [...selected, option],
    );
  }

  function toggleFamilyExpanded(family: string) {
    setExpandedFamilies((current) => {
      const group = visibleGroups.find((item) => item.family === family);
      const defaultExpanded = group
        ? group.selectedCount > 0 || group.options.length <= 6
        : false;
      const isExpanded = current[family] ?? defaultExpanded;
      return {
        ...current,
        [family]: !isExpanded,
      };
    });
  }

  function isFamilyExpanded(group: StrategyGroup) {
    if (normalizedQuery) {
      return true;
    }

    const override = expandedFamilies[group.family];
    if (override !== undefined) {
      return override;
    }

    return group.selectedCount > 0 || group.options.length <= 6;
  }

  function setAllVisibleFamilies(expanded: boolean) {
    setExpandedFamilies((current) => {
      const next = { ...current };
      for (const group of visibleGroups) {
        next[group.family] = expanded;
      }
      return next;
    });
  }

  function selectGroup(group: StrategyGroup) {
    applySelection([...selected, ...group.options]);
  }

  function clearGroup(group: StrategyGroup) {
    applySelection(selected.filter((option) => !group.options.includes(option)));
  }

  function applyBulkAdd() {
    const values = parseBulkValues(bulkInput);
    const unique = Array.from(new Set(values));

    if (unique.length === 0) {
      setBulkFeedback("Paste one or more exact strategy names to add them.");
      return;
    }

    const matched = unique.filter((value) => optionSet.has(value));
    const missing = unique.filter((value) => !optionSet.has(value));
    let added = 0;

    for (const value of matched) {
      if (!selectedSet.has(value)) {
        added += 1;
      }
    }

    if (matched.length > 0) {
      applySelection([...selected, ...matched]);
    }

    const feedbackParts = [
      `${added} added`,
      `${matched.length - added} already selected`,
    ];

    if (missing.length > 0) {
      feedbackParts.push(`${missing.length} not found`);
    }

    setBulkFeedback(feedbackParts.join(" | "));
  }

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-950/50 p-4 space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <label className="text-xs text-gray-500 block mb-1">{label}</label>
          <p className="text-xs text-gray-500">
            {selected.length} selected | {visibleCount} visible across {visibleGroups.length} families
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <div>
            <label className="text-[11px] text-gray-500 block mb-1">Search</label>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={searchPlaceholder}
              className="w-full rounded border border-gray-700 bg-gray-900 px-3 py-1.5 text-sm"
            />
          </div>

          <div>
            <label className="text-[11px] text-gray-500 block mb-1">Scope</label>
            <select
              value={scopeMode}
              onChange={(event) => setScopeMode(event.target.value as ScopeMode)}
              className="w-full rounded border border-gray-700 bg-gray-900 px-3 py-1.5 text-sm"
            >
              <option value="all">All</option>
              <option value="selected">Selected only</option>
              <option value="unselected">Unselected only</option>
            </select>
          </div>

          <div>
            <label className="text-[11px] text-gray-500 block mb-1">Sort</label>
            <select
              value={sortMode}
              onChange={(event) => setSortMode(event.target.value as SortMode)}
              className="w-full rounded border border-gray-700 bg-gray-900 px-3 py-1.5 text-sm"
            >
              <option value="selected-first">Selected first</option>
              <option value="name-asc">Family A-Z</option>
              <option value="name-desc">Family Z-A</option>
            </select>
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-gray-800 bg-gray-900/70 px-3 py-3">
        <div className="flex items-center justify-between gap-3 mb-2">
          <span className="text-xs font-medium uppercase tracking-wide text-gray-400">
            Selected
          </span>
          {selected.length > 0 && (
            <button
              type="button"
              onClick={() => {
                applySelection([]);
              }}
              className="text-xs text-red-300 hover:text-red-200"
            >
              Clear all
            </button>
          )}
        </div>

        {selectedSorted.length === 0 ? (
          <p className="text-xs text-gray-500">No strategies selected.</p>
        ) : (
          <div className="flex flex-wrap gap-2 max-h-28 overflow-y-auto pr-1">
            {selectedSorted.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => toggleOption(item)}
                className="rounded-full border border-blue-700 bg-blue-950/60 px-2.5 py-1 text-xs text-blue-100 hover:border-blue-600"
              >
                {item}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="rounded-lg border border-gray-800 bg-gray-900/50 p-3 space-y-2">
        <div className="flex items-center justify-between gap-3">
          <label className="text-xs font-medium uppercase tracking-wide text-gray-400">
            Bulk Add
          </label>
          <button
            type="button"
            onClick={applyBulkAdd}
            className="rounded border border-gray-700 px-2.5 py-1 text-xs text-gray-200 hover:bg-gray-800"
          >
            Add names
          </button>
        </div>

        <textarea
          value={bulkInput}
          onChange={(event) => setBulkInput(event.target.value)}
          rows={3}
          placeholder="Paste exact strategy names separated by commas, spaces, or new lines"
          className="w-full rounded border border-gray-700 bg-gray-950 px-3 py-2 text-sm"
        />

        {bulkFeedback && <p className="text-xs text-gray-500">{bulkFeedback}</p>}
      </div>

      {visibleGroups.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-800 px-4 py-6 text-sm text-gray-500">
          {emptyText}
        </div>
      ) : (
        <div className="rounded-lg border border-gray-800 bg-gray-900/30 overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-800 px-3 py-2 text-xs text-gray-500">
            <span>Families auto-expand while searching.</span>
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => setAllVisibleFamilies(true)}
                className="text-gray-300 hover:text-white"
              >
                Expand all
              </button>
              <button
                type="button"
                onClick={() => setAllVisibleFamilies(false)}
                className="text-gray-300 hover:text-white"
              >
                Collapse all
              </button>
            </div>
          </div>

          <div className="max-h-[34rem] overflow-y-auto p-2 space-y-2">
            {visibleGroups.map((group) => {
              const expanded = isFamilyExpanded(group);

              return (
                <div
                  key={group.family}
                  className="rounded-lg border border-gray-800 bg-gray-950/50"
                >
                  <div className="flex flex-wrap items-center gap-3 px-3 py-2">
                    <button
                      type="button"
                      onClick={() => toggleFamilyExpanded(group.family)}
                      className="text-left text-sm font-medium text-gray-100 hover:text-white"
                    >
                      {expanded ? "v" : ">"} {group.family}
                    </button>

                    <span className="text-xs text-gray-500">
                      {group.selectedCount}/{group.options.length} selected
                    </span>

                    <div className="ml-auto flex items-center gap-3 text-xs">
                      <button
                        type="button"
                        onClick={() => selectGroup(group)}
                        className="text-blue-300 hover:text-blue-200"
                      >
                        Select group
                      </button>
                      <button
                        type="button"
                        onClick={() => clearGroup(group)}
                        className="text-gray-400 hover:text-gray-200"
                      >
                        Clear group
                      </button>
                    </div>
                  </div>

                  {expanded && (
                    <div className="border-t border-gray-800 px-2 py-2">
                      <div className="grid gap-1 sm:grid-cols-2 2xl:grid-cols-3">
                        {group.options.map((option) => {
                          const checked = selectedSet.has(option);

                          return (
                            <label
                              key={option}
                              className={`flex items-start gap-2 rounded px-2 py-1.5 text-sm transition-colors ${
                                checked
                                  ? "bg-blue-950/30 text-blue-50"
                                  : "text-gray-300 hover:bg-gray-800/70"
                              }`}
                            >
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={() => toggleOption(option)}
                                className="mt-0.5"
                              />
                              <span className="break-all">{option}</span>
                            </label>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export { StrategyMultiSelect };
export default StrategyMultiSelect;
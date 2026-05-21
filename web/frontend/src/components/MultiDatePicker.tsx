import { DayPicker } from "react-day-picker";
import "react-day-picker/style.css";

interface MultiDatePickerProps {
  value: string[];
  onChange: (dates: string[]) => void;
  className?: string;
}

function toDate(value: string): Date {
  const parts = value.split("-");
  if (parts.length !== 3) {
    return new Date(Number.NaN);
  }

  const year = Number(parts[0]);
  const month = Number(parts[1]);
  const day = Number(parts[2]);
  if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) {
    return new Date(Number.NaN);
  }

  return new Date(year, month - 1, day);
}

function toIsoDate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function sortDates(values: string[]): string[] {
  return [...values].sort((left, right) => left.localeCompare(right));
}

export default function MultiDatePicker({
  value,
  onChange,
  className,
}: MultiDatePickerProps) {
  const selectedDates = value
    .map(toDate)
    .filter((date) => !Number.isNaN(date.getTime()));

  return (
    <div className={`rounded border border-gray-800 bg-gray-950/40 px-3 py-3 ${className ?? ""}`.trim()}>
      <div className="launch-date-picker overflow-x-auto">
        <DayPicker
          animate
          fixedWeeks
          mode="multiple"
          numberOfMonths={2}
          pagedNavigation
          selected={selectedDates}
          showOutsideDays
          onSelect={(dates) =>
            onChange(sortDates((dates ?? []).map((date) => toIsoDate(date))))
          }
        />
      </div>

      <div className="mt-3 flex items-center justify-between gap-3 text-xs text-gray-500">
        <span>
          {value.length === 0
            ? "No launch dates selected."
            : `${value.length} launch dates selected.`}
        </span>
        {value.length > 0 && (
          <button
            type="button"
            onClick={() => onChange([])}
            className="rounded border border-gray-700 px-2 py-1 text-gray-300 hover:border-gray-500 hover:text-white"
          >
            Clear
          </button>
        )}
      </div>

      {value.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {value.map((date) => (
            <button
              key={date}
              type="button"
              onClick={() => onChange(value.filter((item) => item !== date))}
              className="rounded-full border border-emerald-900 bg-emerald-950/40 px-3 py-1 text-xs text-emerald-200 hover:border-emerald-700 hover:text-emerald-100"
            >
              {date} ×
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
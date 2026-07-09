"use client";

import { StatusBadge } from "@/components/crm/CRMBadge";
import { FieldViewProps, FieldEditProps } from "../types";

type NormalizedOption = {
  value: string;
  label: string;
  color?: string;
};

function normalizeOptions(options: unknown): NormalizedOption[] {
  if (!Array.isArray(options)) return [];

  return options.flatMap((option): NormalizedOption[] => {
    if (typeof option === "string" || typeof option === "number") {
      const value = String(option);
      return value ? [{ value, label: value }] : [];
    }

    if (!option || typeof option !== "object") return [];

    const raw = option as Record<string, unknown>;
    const valueSource = raw.value ?? raw.label;
    const labelSource = raw.label ?? raw.value;

    if (valueSource === undefined && labelSource === undefined) return [];

    return [{
      value: String(valueSource ?? labelSource),
      label: String(labelSource ?? valueSource),
      color: typeof raw.color === "string" ? raw.color : undefined,
    }];
  });
}

/** Variants: "pills" (default), "comma_text", "count_badge" */
export function MultiSelectFieldView({ value, config, surface, displayConfig }: FieldViewProps) {
  const variant = displayConfig?.variant;
  const options = normalizeOptions(config.options);

  if (value === null || value === undefined) {
    return <span className="text-muted-foreground">{surface === "highlights" ? "Not set" : "—"}</span>;
  }
  const values = Array.isArray(value) ? value : [value];
  if (values.length === 0) {
    return <span className="text-muted-foreground">—</span>;
  }

  // Comma-separated text
  if (variant === "comma_text") {
    const labels = values.map((v) => {
      const option = options.find((o) => o.value === String(v));
      return option?.label || String(v);
    });
    return <span className="text-sm text-foreground truncate">{labels.join(", ")}</span>;
  }

  // Count badge
  if (variant === "count_badge") {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-purple-500/15 text-purple-400">
        {values.length} selected
      </span>
    );
  }

  // Default pills
  return (
    <div className="flex flex-wrap gap-1">
      {values.map((v) => {
        const option = options.find((o) => o.value === String(v));
        return (
          <StatusBadge
            key={String(v)}
            label={option?.label || String(v)}
            color={option?.color || "#6366f1"}
            size="sm"
          />
        );
      })}
    </div>
  );
}

export function MultiSelectFieldEdit({ value, config, onChange }: FieldEditProps) {
  const selected = Array.isArray(value) ? (value as string[]) : [];
  const options = normalizeOptions(config.options);

  const toggle = (optValue: string) => {
    if (selected.includes(optValue)) {
      onChange(selected.filter((v) => v !== optValue));
    } else {
      onChange([...selected, optValue]);
    }
  };

  return (
    <div className="space-y-1.5">
      {options.map((opt) => (
        <label key={opt.value} className="flex items-center gap-2 cursor-pointer text-sm">
          <input
            type="checkbox"
            checked={selected.includes(opt.value)}
            onChange={() => toggle(opt.value)}
            className="w-4 h-4 rounded border-border bg-accent text-purple-500 focus:ring-purple-500"
          />
          <span className="text-foreground">{opt.label}</span>
        </label>
      ))}
    </div>
  );
}

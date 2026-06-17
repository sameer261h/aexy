"use client";

import { cn } from "@/lib/utils";

type SpinnerSize = "xs" | "sm" | "md" | "lg";

const SIZE_TO_CLASS: Record<SpinnerSize, string> = {
  xs: "h-6 w-6 border-2",
  sm: "h-8 w-8 border-[3px]",
  md: "h-10 w-10 border-4",
  lg: "h-12 w-12 border-4",
};

interface SpinnerProps {
  size?: SpinnerSize;
  /** Used by assistive tech; rendered as `sr-only`. Defaults to "Loading". */
  label?: string;
  className?: string;
}

/**
 * Double-ring loading spinner. Replaces four near-identical inline
 * implementations across the docs surface (and growing — pull this
 * into other modules as their spinners come up for refactor).
 *
 *   - `role="status"` + `aria-label` so screen-reader users hear it.
 *   - `data-testid="aexy-spinner"` so E2E tests can assert "is the
 *     app showing a loading state" without coupling to css details.
 */
export function Spinner({ size = "md", label, className }: SpinnerProps) {
  const dims = SIZE_TO_CLASS[size];
  return (
    <div
      role="status"
      aria-label={label ?? "Loading"}
      data-testid="aexy-spinner"
      className={cn("relative inline-block", className)}
    >
      <div className={cn(dims, "border-primary-500/20 rounded-full")} />
      <div
        className={cn(
          dims,
          "border-primary-500 border-t-transparent rounded-full animate-spin absolute inset-0",
        )}
      />
      <span className="sr-only">{label ?? "Loading"}</span>
    </div>
  );
}

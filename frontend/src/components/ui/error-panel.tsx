"use client";

import { AlertTriangle, Loader2, RotateCcw } from "lucide-react";

interface ErrorPanelProps {
  /** The error caught from a fetch. We surface its message in dev. */
  error?: unknown;
  /** Headline shown to all users. Defaults to a generic "Something
   *  went wrong". */
  title?: string;
  /** Optional one-line description shown under the headline. */
  description?: string;
  /** Retry handler. When provided, a "Try again" button renders. */
  onRetry?: () => void | Promise<void>;
  /** When true, the retry button shows a spinner. Useful when the
   *  caller's refetch is async and the panel sticks around briefly. */
  isRetrying?: boolean;
  /** Wrapping container className override. */
  className?: string;
}

function extractDetail(error: unknown): string | null {
  if (!error) return null;
  if (typeof error === "string") return error;
  // axios-style error shape that recurs across the reviewsApi calls.
  const detail = (
    error as { response?: { data?: { detail?: string } }; message?: string }
  )?.response?.data?.detail;
  if (detail) return detail;
  const message = (error as { message?: string })?.message;
  return message ?? null;
}

/**
 * Standardized error display for failed list / detail fetches. Shared
 * across the reviews surface to replace the four near-duplicate
 * "Failed to load X" + retry-link snippets, each with slightly
 * different copy and color choices.
 *
 * Dev builds (`process.env.NODE_ENV !== "production"`) also surface
 * the underlying detail / message so the engineer doesn't have to dig
 * into devtools to identify which endpoint failed.
 */
export function ErrorPanel({
  error,
  title = "Something went wrong",
  description,
  onRetry,
  isRetrying,
  className,
}: ErrorPanelProps) {
  const detail = extractDetail(error);
  const isDev = process.env.NODE_ENV !== "production";
  return (
    <div
      role="alert"
      className={
        className ??
        "bg-background/50 rounded-xl border border-border p-8 text-center"
      }
    >
      <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-red-500/10 mb-3">
        <AlertTriangle className="h-6 w-6 text-red-500 dark:text-red-400" />
      </div>
      <p className="text-foreground font-medium mb-1">{title}</p>
      {description && (
        <p className="text-sm text-muted-foreground mb-3">{description}</p>
      )}
      {isDev && detail && (
        <p className="text-xs text-muted-foreground font-mono mb-3 max-w-md mx-auto break-words">
          {detail}
        </p>
      )}
      {onRetry && (
        <button
          onClick={() => onRetry()}
          disabled={isRetrying}
          className="inline-flex items-center gap-2 mt-2 px-4 py-2 text-sm rounded-lg bg-accent hover:bg-muted text-foreground transition disabled:opacity-50"
        >
          {isRetrying ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RotateCcw className="h-4 w-4" />
          )}
          Try again
        </button>
      )}
    </div>
  );
}

/**
 * Date / time helpers shared across the agent / automation / operations
 * surfaces.
 *
 * Pre-this module, three different relative-time implementations lived
 * in the code base — operations/page.tsx, agents/[agentId]/inbox/page.tsx,
 * and components/workflow-builder/VersionHistory.tsx — with subtly
 * different thresholds and labels. Centralizing them here keeps the
 * agent detail "last run 3h ago" and the automation card "Last run 3h
 * ago" reading identically.
 */

/**
 * Compact relative time string for "happened in the recent past".
 * Returns:
 *   "just now"     <1 min ago
 *   "5m ago"       <1 hour ago
 *   "3h ago"       <1 day ago
 *   "2d ago"       <30 days ago
 *   "Mar 5"        further than that (short month + day)
 *
 * Returns an empty string when `value` is null/undefined/invalid so
 * the consumer doesn't need a separate guard.
 */
export function formatRelative(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const diff = Date.now() - date.getTime();
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  if (diff < 2_592_000_000) return `${Math.floor(diff / 86_400_000)}d ago`;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/**
 * Absolute time for tooltip / details views. Honors the user's locale.
 * Returns an empty string for null/invalid input.
 */
export function formatAbsolute(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Date-only variant for table cells, deadline badges, and member
 * cards. Honors the active locale by passing `undefined` to Intl —
 * which falls back to the browser's resolved locale (Next/next-intl
 * keeps this in sync with the user's cookie). The shape mirrors what
 * most reviews surface widgets were rendering by hand:
 * `Mar 5, 2026`.
 */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/**
 * Short variant for inline pills / breadcrumbs where the year is
 * obvious from context. Renders `Mar 5`.
 */
/**
 * Returns an error string if the date range is inverted, else `null`. Centralised
 * here because the same check is repeated across every task-create surface
 * (project board modal, backlog inline modal, workspace all-tasks modal).
 */
export function validateDateRange(
  start: string | null | undefined,
  end: string | null | undefined,
): string | null {
  if (!start || !end) return null;
  if (new Date(end) < new Date(start)) return "End date must be after the start date.";
  return null;
}


export function formatDateShort(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

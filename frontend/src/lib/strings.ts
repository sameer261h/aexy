/**
 * Utility string helpers used across the app.
 *
 * Each is meant to replace an inline expression that's both common
 * and easy to get subtly wrong (e.g. an `.split(" ").map(n => n[0])`
 * that yields 3 initials for "Anna Marie Smith" or 1 for "Cher",
 * which is the bug `UX-RV-MGR-009` flagged).
 */

/**
 * Two-letter initials from a name, slicing at most two whitespace-
 * separated tokens and uppercased. Returns "?" for empty input so
 * avatar UI never renders an empty circle.
 *
 * Examples:
 *   getInitials("Anna Marie Smith") === "AM"
 *   getInitials("Cher")             === "C"
 *   getInitials("  ")               === "?"
 *   getInitials(undefined)          === "?"
 */
export function getInitials(name: string | null | undefined): string {
  if (!name) return "?";
  const initials = name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((token) => token[0] ?? "")
    .join("")
    .toUpperCase();
  return initials || "?";
}

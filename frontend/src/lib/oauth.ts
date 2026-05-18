/**
 * Marks an OAuth flow as being initiated by *this* browser tab, so the
 * /auth/callback handler can distinguish "the user clicked Login from our
 * site" from "an attacker sent the user a `/auth/callback?token=...` link".
 *
 * Without this gate, anyone with a leaked or attacker-chosen JWT can craft
 * a `/auth/callback?token=ATTACKER_JWT` URL, send it to a victim, and
 * silently plant their session in the victim's localStorage. Same shape
 * as the WS-071 fix on `/p/[publicSlug]`.
 */

export const OAUTH_INFLIGHT_KEY = "oauthInflight";

export function markOAuthInflight(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(OAUTH_INFLIGHT_KEY, "1");
  } catch {
    // sessionStorage can throw in sandboxed iframes; the callback will
    // simply reject the token in that case, which is the safe default.
  }
}

export function consumeOAuthInflight(): boolean {
  if (typeof window === "undefined") return false;
  try {
    const value = window.sessionStorage.getItem(OAUTH_INFLIGHT_KEY);
    window.sessionStorage.removeItem(OAUTH_INFLIGHT_KEY);
    return value === "1";
  } catch {
    return false;
  }
}

/**
 * Pattern that matches the backend's OAuth-initiation routes.
 * `/auth/<provider>/login` and `/auth/<provider>/connect`.
 */
const OAUTH_INIT_PATTERN = /\/auth\/[a-z0-9_-]+\/(login|connect|connect-crm)\b/i;

function isOAuthInitUrl(href: string | null | undefined): boolean {
  if (!href) return false;
  return OAUTH_INIT_PATTERN.test(href);
}

/**
 * Document-level click listener that watches for clicks on any element
 * navigating to an OAuth initiation URL (whether via `<a href>` or
 * `window.location.assign`-style buttons) and sets the inflight marker
 * just before the navigation happens.
 *
 * Mounted once at the app root via <OAuthInflightTagger />.
 */
export function installOAuthClickInterceptor(): () => void {
  if (typeof window === "undefined") return () => {};

  const handler = (event: MouseEvent) => {
    // Capture-phase listener; runs before navigation.
    const target = event.target;
    if (!(target instanceof Element)) return;

    const anchor = target.closest<HTMLAnchorElement>("a[href]");
    if (anchor && isOAuthInitUrl(anchor.getAttribute("href"))) {
      markOAuthInflight();
    }
  };

  // mousedown fires before the navigation triggered by the click.
  // Use capture so we run even if a child element's listener calls
  // stopPropagation.
  document.addEventListener("mousedown", handler, true);
  return () => document.removeEventListener("mousedown", handler, true);
}

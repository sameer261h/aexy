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

/**
 * Where to send the user once they're authed. Set by the landing page when
 * the middleware redirected them with `?next=...`; consumed by `setToken`
 * after the OAuth callback succeeds.
 */
export const POST_LOGIN_REDIRECT_KEY = "postLoginRedirect";

/**
 * Returns the value only if it's a same-origin internal path. Rejects
 * absolute URLs, protocol-relative URLs, and anything that doesn't start
 * with a single `/`. Without this, `?next=//evil.com` would be an open
 * redirect into a phishing page.
 */
export function safeInternalPath(value: string | null | undefined): string | null {
  if (!value || typeof value !== "string") return null;
  if (!value.startsWith("/")) return null;
  if (value.startsWith("//")) return null; // protocol-relative
  if (value.startsWith("/\\")) return null; // some browsers treat as protocol-relative
  return value;
}

export function stashPostLoginRedirect(value: string | null | undefined): void {
  if (typeof window === "undefined") return;
  const safe = safeInternalPath(value);
  if (!safe) return;
  try {
    window.sessionStorage.setItem(POST_LOGIN_REDIRECT_KEY, safe);
  } catch {
    // sandboxed; ignore
  }
}

export function consumePostLoginRedirect(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const value = window.sessionStorage.getItem(POST_LOGIN_REDIRECT_KEY);
    window.sessionStorage.removeItem(POST_LOGIN_REDIRECT_KEY);
    return safeInternalPath(value);
  } catch {
    return null;
  }
}

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
 * Document-level listeners that watch for any navigation to an OAuth
 * initiation URL and set the inflight marker just before the navigation
 * happens. Three vectors are covered:
 *
 *  - Mouse clicks on `<a href>` → mousedown (capture)
 *  - Keyboard activation (Tab + Enter / Space) on focused anchors → keydown
 *  - Programmatic navigation via `window.location.assign|replace|href`
 *
 * Without the keyboard + programmatic paths, OAuth login is broken for
 * keyboard-only users and any JS-driven login button.
 *
 * Mounted once at the app root via <OAuthInflightTagger />.
 */
export function installOAuthClickInterceptor(): () => void {
  if (typeof window === "undefined") return () => {};

  const markIfAnchorMatches = (target: EventTarget | null) => {
    if (!(target instanceof Element)) return;
    const anchor = target.closest<HTMLAnchorElement>("a[href]");
    if (anchor && isOAuthInitUrl(anchor.getAttribute("href"))) {
      markOAuthInflight();
    }
  };

  // mousedown fires before the navigation triggered by the click.
  // Capture-phase so a child's stopPropagation can't suppress us.
  const mouseHandler = (event: MouseEvent) => markIfAnchorMatches(event.target);
  // Keyboard activation: Enter or Space on a focused anchor triggers
  // navigation but never fires mousedown.
  const keyHandler = (event: KeyboardEvent) => {
    if (event.key !== "Enter" && event.key !== " " && event.key !== "Spacebar") return;
    markIfAnchorMatches(event.target);
  };

  document.addEventListener("mousedown", mouseHandler, true);
  document.addEventListener("keydown", keyHandler, true);

  // Programmatic navigation: wrap location.assign/replace and the
  // location.href setter. Any caller that pushes the user to an OAuth
  // init URL via JS now also sets the inflight marker.
  const originalAssign = window.location.assign.bind(window.location);
  const originalReplace = window.location.replace.bind(window.location);
  const hrefDescriptor = Object.getOwnPropertyDescriptor(
    window.Location.prototype,
    "href",
  );

  let hrefRestore: (() => void) | null = null;
  try {
    window.location.assign = ((url: string | URL) => {
      if (isOAuthInitUrl(String(url))) markOAuthInflight();
      return originalAssign(url);
    }) as typeof window.location.assign;
    window.location.replace = ((url: string | URL) => {
      if (isOAuthInitUrl(String(url))) markOAuthInflight();
      return originalReplace(url);
    }) as typeof window.location.replace;

    if (hrefDescriptor && hrefDescriptor.set) {
      const originalHrefSet = hrefDescriptor.set;
      const patchedDescriptor: PropertyDescriptor = {
        configurable: true,
        enumerable: hrefDescriptor.enumerable ?? false,
        get: hrefDescriptor.get,
        set(value: string) {
          if (isOAuthInitUrl(String(value))) markOAuthInflight();
          originalHrefSet.call(this, value);
        },
      };
      Object.defineProperty(window.Location.prototype, "href", patchedDescriptor);
      hrefRestore = () => {
        Object.defineProperty(window.Location.prototype, "href", hrefDescriptor);
      };
    }
  } catch {
    // Some browser sandboxes forbid mutating location; fall back to
    // mouse/keyboard handlers only.
  }

  return () => {
    document.removeEventListener("mousedown", mouseHandler, true);
    document.removeEventListener("keydown", keyHandler, true);
    try {
      window.location.assign = originalAssign;
      window.location.replace = originalReplace;
      if (hrefRestore) hrefRestore();
    } catch {
      // best-effort cleanup
    }
  };
}

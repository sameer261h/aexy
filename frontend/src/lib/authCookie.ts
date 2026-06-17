/**
 * Middleware-visible "presence" cookie that mirrors the auth-token state.
 *
 * The actual JWT lives in localStorage and is what the API verifies. The
 * cookie exists ONLY so the Next.js middleware (which can't read
 * localStorage) can decide whether to render the authenticated shell. If
 * the cookie and localStorage disagree, the middleware will redirect
 * `/dashboard` to `/?next=/dashboard`, which is the loop that bit us when
 * the landing page redirected to /dashboard without first syncing the
 * cookie.
 */
export const AUTH_PRESENCE_COOKIE = "aexy_authed";

function secureAttr(): string {
  if (typeof window === "undefined") return "";
  return window.location.protocol === "https:" ? "; Secure" : "";
}

export function setAuthPresenceCookie(): void {
  if (typeof document === "undefined") return;
  document.cookie = `${AUTH_PRESENCE_COOKIE}=1; path=/; SameSite=Lax${secureAttr()}`;
}

export function clearAuthPresenceCookie(): void {
  if (typeof document === "undefined") return;
  document.cookie = `${AUTH_PRESENCE_COOKIE}=; path=/; SameSite=Lax; max-age=0${secureAttr()}`;
}

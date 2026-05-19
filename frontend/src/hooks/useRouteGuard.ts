"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

/**
 * Pop a confirmation prompt before letting the user leave a page with
 * unsaved changes.
 *
 * Why this is anchor-click intercept rather than a router event:
 * Next.js App Router (>=13) doesn't expose `router.events` like the
 * Pages Router did, so there's no clean way to subscribe to all
 * navigations. The next-best pattern is to capture clicks on
 * `<a>` elements (which is what `next/link` renders under the hood)
 * and intercept *before* the framework router takes over. Programmatic
 * `router.push()` calls aren't catchable this way — guarded surfaces
 * should call `requestConfirm(path)` directly before navigating in
 * code.
 *
 * Companion `beforeunload` handler covers hard refresh / tab close.
 *
 * Returns a `requestConfirm` helper so code paths that DO push
 * programmatically (toolbar shortcuts, form-success redirects) can opt
 * into the same prompt without duplicating logic.
 */

interface UseRouteGuardOptions {
  /** Active when true; ignored otherwise. */
  enabled: boolean;
  /** Optional override for the browser beforeunload guard. Defaults to the
   *  same `enabled` flag — most callers want both. */
  beforeUnload?: boolean;
}

interface RouteGuardState {
  /** True while a confirmation prompt is pending the user's choice. */
  pendingHref: string | null;
  /** Confirm the pending navigation. Caller is responsible for clearing
   *  the dirty flag before this resolves (so a re-entry doesn't fire). */
  confirmPending: () => void;
  /** Dismiss the prompt, stay on the current page. */
  cancelPending: () => void;
  /** Imperative API for code paths that do programmatic navigation. */
  requestConfirm: (href: string) => void;
}

export function useRouteGuard({
  enabled,
  beforeUnload = true,
}: UseRouteGuardOptions): RouteGuardState {
  const router = useRouter();
  const [pendingHref, setPendingHref] = useState<string | null>(null);
  // Keep the latest enabled flag in a ref so the click handler closure
  // doesn't go stale between renders.
  const enabledRef = useRef(enabled);
  useEffect(() => {
    enabledRef.current = enabled;
  }, [enabled]);

  // beforeunload: hard refresh / tab close.
  useEffect(() => {
    if (!enabled || !beforeUnload) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [enabled, beforeUnload]);

  // Anchor click intercept.
  useEffect(() => {
    const handler = (event: MouseEvent) => {
      if (!enabledRef.current) return;
      // Respect modifier-key intent (cmd/ctrl/shift-click → new tab,
      // middle-click, right-click). Those don't navigate the current
      // tab, so no dirty-data risk.
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      ) {
        return;
      }
      const target = event.target as HTMLElement | null;
      const anchor = target?.closest("a") as HTMLAnchorElement | null;
      if (!anchor) return;
      const href = anchor.getAttribute("href");
      if (!href || href.startsWith("#")) return;
      // External links go through the normal browser flow + the
      // beforeunload guard above. We only care about same-origin
      // navigations the framework handles.
      const url = new URL(anchor.href, window.location.href);
      if (url.origin !== window.location.origin) return;
      const target_attr = anchor.getAttribute("target");
      if (target_attr && target_attr !== "_self") return;
      // Same-page (hash-only) navigations don't dirty anything.
      if (
        url.pathname === window.location.pathname &&
        url.search === window.location.search
      ) {
        return;
      }
      event.preventDefault();
      setPendingHref(url.pathname + url.search + url.hash);
    };
    document.addEventListener("click", handler, true);
    return () => document.removeEventListener("click", handler, true);
  }, []);

  const confirmPending = () => {
    const href = pendingHref;
    setPendingHref(null);
    if (href) router.push(href);
  };

  const cancelPending = () => setPendingHref(null);

  const requestConfirm = (href: string) => {
    if (!enabledRef.current) {
      router.push(href);
      return;
    }
    setPendingHref(href);
  };

  return {
    pendingHref,
    confirmPending,
    cancelPending,
    requestConfirm,
  };
}

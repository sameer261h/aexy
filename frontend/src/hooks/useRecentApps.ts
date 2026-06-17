"use client";

import { useEffect, useMemo, useRef } from "react";
import { usePathname } from "next/navigation";

import { useRecentAppsStore } from "@/stores/recentAppsStore";
import {
  APP_CATALOG,
  AppDefinition,
  getAppIdFromPath,
} from "@/config/appDefinitions";

interface UseRecentAppsOptions {
  /** Optional access filter — entries for inaccessible apps are dropped. */
  isAppAccessible?: (appId: string) => boolean;
  /** Max entries to surface. Defaults to all stored entries (8 cap from store). */
  limit?: number;
  /** When true, record the current pathname as a visit. Defaults to true. */
  record?: boolean;
}

/**
 * Track the user's recently-visited apps in localStorage and surface them
 * resolved against the APP_CATALOG. Pass an access filter to hide apps the
 * user no longer has access to (e.g. after a role change).
 */
export function useRecentApps(options: UseRecentAppsOptions = {}) {
  const { isAppAccessible, limit, record = true } = options;
  const pathname = usePathname();
  const recent = useRecentAppsStore((s) => s.recent);
  const recordVisit = useRecentAppsStore((s) => s.recordVisit);

  // Guard against duplicate writes during the same path render — Next's
  // App Router can fire pathname-stable re-renders that would otherwise
  // bump the timestamp on every keystroke or query change.
  const lastRecordedRef = useRef<string | null>(null);

  useEffect(() => {
    if (!record) return;
    const appId = pathname ? getAppIdFromPath(pathname) : undefined;
    if (!appId) return;
    if (lastRecordedRef.current === appId) return;
    lastRecordedRef.current = appId;
    recordVisit(appId);
  }, [pathname, record, recordVisit]);

  const recentApps = useMemo<AppDefinition[]>(() => {
    const out: AppDefinition[] = [];
    for (const entry of recent) {
      const app = APP_CATALOG[entry.appId];
      if (!app) continue;
      if (isAppAccessible && !isAppAccessible(entry.appId)) continue;
      out.push(app);
      if (limit && out.length >= limit) break;
    }
    return out;
  }, [recent, isAppAccessible, limit]);

  return { recentApps };
}

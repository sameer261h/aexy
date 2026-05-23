import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface RecentAppEntry {
  appId: string;
  lastVisitedAt: number;
}

const MAX_RECENT = 8;

interface RecentAppsState {
  recent: RecentAppEntry[];
  recordVisit: (appId: string) => void;
  clear: () => void;
}

export const useRecentAppsStore = create<RecentAppsState>()(
  persist(
    (set, get) => ({
      recent: [],
      recordVisit: (appId: string) => {
        const now = Date.now();
        const prev = get().recent;
        const without = prev.filter((e) => e.appId !== appId);
        const next = [{ appId, lastVisitedAt: now }, ...without].slice(0, MAX_RECENT);
        set({ recent: next });
      },
      clear: () => set({ recent: [] }),
    }),
    { name: "aexy-recent-apps" }
  )
);

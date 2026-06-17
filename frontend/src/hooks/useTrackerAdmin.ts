"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { TrackerTimesheetResponse } from "@/hooks/useTrackerTimesheet";

// Aexy Tracker — admin/config hooks.
// Backend: api/tracker_admin.py
//   GET/PUT /tracker/admin/projects/{id}/config
//   GET     /tracker/admin/projects?workspace_id=
//   GET     /tracker/admin/timesheet?workspace_id=&developer_id=&start=&end=

export interface TrackerCaptureConfig {
  sample_interval_s: number;
  screenshot_policy: "off" | "active_window" | "full_screen";
  screenshot_every_n_samples: number;
  idle_threshold_s: number;
  paused: boolean;
  excluded_bundle_ids: string[];
}

export interface TrackerProjectConfig {
  project_id: string;
  enabled: boolean;
  config: TrackerCaptureConfig;
}

export interface TrackerAdminProject {
  id: string;
  name: string;
  slug: string;
  enabled: boolean;
  device_count: number;
  active_devices: number;
}

export const DEFAULT_CAPTURE_CONFIG: TrackerCaptureConfig = {
  sample_interval_s: 60,
  screenshot_policy: "off",
  screenshot_every_n_samples: 5,
  idle_threshold_s: 300,
  paused: false,
  excluded_bundle_ids: [],
};

// Per-project config (gated server-side by can_edit_projects).
export function useProjectTrackerConfig(projectId: string | null) {
  return useQuery<TrackerProjectConfig>({
    queryKey: ["tracker", "admin", "config", projectId],
    queryFn: async () => {
      const res = await api.get(`/tracker/admin/projects/${projectId}/config`);
      return res.data;
    },
    enabled: !!projectId,
  });
}

export function useUpdateProjectTrackerConfig(projectId: string) {
  const qc = useQueryClient();
  return useMutation<
    TrackerProjectConfig,
    unknown,
    { enabled: boolean; config: TrackerCaptureConfig }
  >({
    mutationFn: async (body) => {
      const res = await api.put(`/tracker/admin/projects/${projectId}/config`, body);
      return res.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tracker", "admin", "config", projectId] });
      qc.invalidateQueries({ queryKey: ["tracker", "admin", "projects"] });
    },
  });
}

// Workspace overview (gated by can_edit_projects OR can_view_tracker_records).
export function useWorkspaceTrackerProjects(workspaceId: string | null) {
  return useQuery<TrackerAdminProject[]>({
    queryKey: ["tracker", "admin", "projects", workspaceId],
    queryFn: async () => {
      const res = await api.get("/tracker/admin/projects", {
        params: { workspace_id: workspaceId },
      });
      return res.data;
    },
    enabled: !!workspaceId,
    retry: false, // a 403 (no permission) shouldn't retry — surface it
  });
}

// Another developer's timesheet (gated by can_view_tracker_records).
export function useAdminTimesheet(
  workspaceId: string | null,
  developerId: string | null,
  range: { start: string; end: string },
) {
  return useQuery<TrackerTimesheetResponse>({
    queryKey: ["tracker", "admin", "timesheet", workspaceId, developerId, range.start, range.end],
    queryFn: async () => {
      const res = await api.get("/tracker/admin/timesheet", {
        params: {
          workspace_id: workspaceId,
          developer_id: developerId,
          start: range.start,
          end: range.end,
        },
      });
      return res.data;
    },
    enabled: !!workspaceId && !!developerId,
    retry: false,
  });
}

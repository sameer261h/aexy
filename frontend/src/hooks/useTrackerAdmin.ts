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

// --------------------------------------------------------------------------- //
// Target hours (workspace default / per-project / per-developer overrides).
// Backend: api/tracker_target.py
//   GET    /tracker/target-hours?workspace_id=
//   PUT    /tracker/target-hours?workspace_id=   body { project_id?, developer_id?, target_hours_per_day }
//   DELETE /tracker/target-hours/{id}?workspace_id=
// --------------------------------------------------------------------------- //
export interface TargetHoursOverride {
  id: string;
  workspace_id: string;
  project_id: string | null;
  developer_id: string | null;
  target_hours_per_day: number;
  level: "workspace" | "project" | "developer";
}

export interface TargetHoursUpsert {
  project_id?: string | null;
  developer_id?: string | null;
  target_hours_per_day: number;
}

export const DEFAULT_TARGET_HOURS = 8;

export function useTargetHours(workspaceId: string | null) {
  return useQuery<TargetHoursOverride[]>({
    queryKey: ["tracker", "target-hours", workspaceId],
    queryFn: async () => {
      const res = await api.get("/tracker/target-hours", {
        params: { workspace_id: workspaceId },
      });
      return res.data;
    },
    enabled: !!workspaceId,
    retry: false,
  });
}

export function useUpsertTargetHours(workspaceId: string | null) {
  const qc = useQueryClient();
  return useMutation<TargetHoursOverride, unknown, TargetHoursUpsert>({
    mutationFn: async (body) => {
      const res = await api.put("/tracker/target-hours", body, {
        params: { workspace_id: workspaceId },
      });
      return res.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tracker", "target-hours", workspaceId] });
    },
  });
}

export function useDeleteTargetHours(workspaceId: string | null) {
  const qc = useQueryClient();
  return useMutation<void, unknown, string>({
    mutationFn: async (id) => {
      await api.delete(`/tracker/target-hours/${id}`, {
        params: { workspace_id: workspaceId },
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tracker", "target-hours", workspaceId] });
    },
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

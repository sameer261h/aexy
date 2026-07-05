"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

// Aexy Tracker — auto-attributed timesheet + Q&A + review actions.
// Backend: api/tracker_qa.py (GET /tracker/timesheet, POST /tracker/qa,
// GET /tracker/candidate-tasks, PATCH /tracker/timesheet/entries/{id}).

export type AttributionStatus =
  | "inferred"
  | "confirmed"
  | "corrected"
  | "dismissed"
  | null;

export interface TrackerTimesheetEntry {
  id: string;
  entry_date: string;
  duration_minutes: number;
  task_id: string | null;
  task_title: string | null;
  description: string | null;
  confidence_score: number | null;
  attribution_status: AttributionStatus;
}

export interface TrackerCandidateTask {
  id: string;
  title: string;
  status: string | null;
}

export type TrackerEntryAction = "confirm" | "correct" | "dismiss";

export interface TrackerTimesheetDay {
  date: string;
  total_minutes: number;
  entries: TrackerTimesheetEntry[];
  journal: string | null;
}

export interface TrackerTimesheetResponse {
  days: TrackerTimesheetDay[];
  total_minutes: number;
  days_count: number;
}

export interface TrackerQAResponse {
  answer: string;
  days: number;
  journals_used: number;
  time_entries_used: number;
}

export function useTrackerTimesheet(range: { start: string; end: string }) {
  return useQuery<TrackerTimesheetResponse>({
    queryKey: ["tracker", "timesheet", range.start, range.end],
    queryFn: async () => {
      const res = await api.get("/tracker/timesheet", {
        params: { start: range.start, end: range.end },
      });
      return res.data;
    },
  });
}

export function useTrackerQA() {
  return useMutation<TrackerQAResponse, unknown, { question: string; days?: number }>({
    mutationFn: async (vars) => {
      const res = await api.post("/tracker/qa", {
        question: vars.question,
        days: vars.days ?? 7,
      });
      return res.data;
    },
  });
}

// The caller's open assigned tasks — choices for correcting an attribution.
export function useTrackerCandidateTasks(enabled = true) {
  return useQuery<TrackerCandidateTask[]>({
    queryKey: ["tracker", "candidate-tasks"],
    queryFn: async () => {
      const res = await api.get("/tracker/candidate-tasks");
      return res.data;
    },
    enabled,
    staleTime: 60_000,
  });
}

// Confirm / correct (reassign) / dismiss an inferred entry. Invalidates the
// timesheet so the row's badge/visibility updates.
export function useUpdateTrackerEntry() {
  const qc = useQueryClient();
  return useMutation<
    { id: string; task_id: string | null; task_title: string | null; attribution_status: AttributionStatus },
    unknown,
    { entryId: string; action: TrackerEntryAction; taskId?: string }
  >({
    mutationFn: async ({ entryId, action, taskId }) => {
      const res = await api.patch(`/tracker/timesheet/entries/${entryId}`, {
        action,
        task_id: taskId ?? null,
      });
      return res.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tracker", "timesheet"] });
    },
  });
}

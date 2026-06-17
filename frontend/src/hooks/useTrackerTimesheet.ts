"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

// Aexy Tracker — auto-attributed timesheet + Q&A.
// Backend: api/tracker_qa.py (GET /tracker/timesheet, POST /tracker/qa).

export interface TrackerTimesheetEntry {
  id: string;
  entry_date: string;
  duration_minutes: number;
  task_id: string | null;
  task_title: string | null;
  description: string | null;
  confidence_score: number | null;
}

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

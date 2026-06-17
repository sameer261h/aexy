"use client";

import { useMemo, useState } from "react";
import {
  Activity,
  Clock,
  CalendarDays,
  ListChecks,
  Sparkles,
  Send,
  Loader2,
} from "lucide-react";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { MetricCard, DateRangePicker, getDefaultDateRange, DateRange } from "@/components/tracking/shared";
import { useTrackerTimesheet, useTrackerQA } from "@/hooks/useTrackerTimesheet";

function fmtDuration(minutes: number) {
  if (!minutes) return "0m";
  if (minutes < 60) return `${Math.round(minutes)}m`;
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

function fmtDay(iso: string) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

function confidenceBadge(score: number | null) {
  if (score == null) return null;
  const pct = Math.round(score * 100);
  const tone =
    pct >= 75
      ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
      : pct >= 50
      ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"
      : "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400";
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${tone}`}>{pct}% conf</span>
  );
}

const toISO = (d: Date) => d.toISOString().split("T")[0];

export default function TrackerTimesheetPage() {
  const [dateRange, setDateRange] = useState<DateRange>(getDefaultDateRange("this_week"));
  const range = { start: toISO(dateRange.startDate), end: toISO(dateRange.endDate) };
  const { data, isLoading } = useTrackerTimesheet(range);

  const [question, setQuestion] = useState("");
  const qa = useTrackerQA();

  const stats = useMemo(() => {
    const days = data?.days || [];
    const totalEntries = days.reduce((s, d) => s + d.entries.length, 0);
    const trackedDays = days.filter((d) => d.total_minutes > 0).length;
    const avg = trackedDays > 0 ? (data?.total_minutes || 0) / trackedDays : 0;
    return { totalEntries, trackedDays, avg };
  }, [data]);

  const askQuestion = (q?: string) => {
    const text = (q ?? question).trim();
    if (!text) return;
    setQuestion(text);
    qa.mutate({ question: text, days: 7 });
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <Breadcrumb
        items={[{ label: "Tracking", href: "/tracking" }, { label: "Tracker" }]}
        className="mb-6"
      />

      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold">
            <Activity className="h-6 w-6 text-blue-500" />
            Auto-attributed Timesheet
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            AI-inferred time from Aexy Tracker — no manual entry. Review and confirm.
          </p>
        </div>
        <DateRangePicker value={dateRange} onChange={setDateRange} />
      </div>

      {/* Metrics */}
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard title="Total tracked" value={fmtDuration(data?.total_minutes || 0)} icon={Clock} />
        <MetricCard title="Days tracked" value={stats.trackedDays} icon={CalendarDays} />
        <MetricCard title="Attributed entries" value={stats.totalEntries} icon={ListChecks} />
        <MetricCard title="Avg / day" value={fmtDuration(stats.avg)} icon={Activity} />
      </div>

      {/* Ask AI */}
      <div className="mb-8 rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-900">
        <div className="mb-2 flex items-center gap-2 text-sm font-medium">
          <Sparkles className="h-4 w-4 text-purple-500" />
          Ask about your work
        </div>
        <div className="flex gap-2">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && askQuestion()}
            placeholder="What did I ship last week? · Draft my standup"
            className="flex-1 rounded-lg border border-gray-300 bg-transparent px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-gray-700"
          />
          <button
            onClick={() => askQuestion()}
            disabled={qa.isPending || !question.trim()}
            className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {qa.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            Ask
          </button>
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
          {["Draft my standup", "What did I ship this week?", "Where did my time go?"].map((s) => (
            <button
              key={s}
              onClick={() => askQuestion(s)}
              className="rounded-full border border-gray-200 px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-400 dark:hover:bg-gray-800"
            >
              {s}
            </button>
          ))}
        </div>
        {qa.data && (
          <div className="mt-3 whitespace-pre-wrap rounded-lg bg-gray-50 p-3 text-sm dark:bg-gray-800">
            {qa.data.answer}
            <div className="mt-2 text-xs text-gray-400">
              Based on {qa.data.journals_used} journal(s) · {qa.data.time_entries_used} time entries
            </div>
          </div>
        )}
        {qa.isError && (
          <div className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-600 dark:bg-red-900/20">
            Couldn&apos;t get an answer. The AI gateway may be unavailable.
          </div>
        )}
      </div>

      {/* Days */}
      {isLoading ? (
        <div className="flex justify-center py-16 text-gray-400">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : !data?.days?.length ? (
        <div className="rounded-xl border border-dashed border-gray-300 py-16 text-center text-gray-500 dark:border-gray-700">
          <Activity className="mx-auto mb-2 h-8 w-8 opacity-40" />
          No tracked activity in this range yet. Install Aexy Tracker to start capturing.
        </div>
      ) : (
        <div className="space-y-4">
          {data.days.map((day) => (
            <div
              key={day.date}
              className="rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-900"
            >
              <div className="mb-2 flex items-center justify-between">
                <h3 className="font-medium">{fmtDay(day.date)}</h3>
                <span className="text-sm text-gray-500">{fmtDuration(day.total_minutes)}</span>
              </div>
              {day.journal && (
                <p className="mb-3 border-l-2 border-blue-400 pl-3 text-sm italic text-gray-600 dark:text-gray-300">
                  {day.journal}
                </p>
              )}
              <ul className="divide-y divide-gray-100 dark:divide-gray-800">
                {day.entries.map((e) => (
                  <li key={e.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium">
                        {e.task_title || "Unattributed"}
                      </div>
                      {e.description && (
                        <div className="truncate text-xs text-gray-400">{e.description}</div>
                      )}
                    </div>
                    {confidenceBadge(e.confidence_score)}
                    <span className="shrink-0 tabular-nums text-gray-500">
                      {fmtDuration(e.duration_minutes)}
                    </span>
                  </li>
                ))}
                {!day.entries.length && (
                  <li className="py-2 text-xs text-gray-400">Journal only — no attributed entries.</li>
                )}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Activity,
  Clock,
  CalendarDays,
  ListChecks,
  Sparkles,
  Send,
  Loader2,
  Check,
  X,
  Pencil,
} from "lucide-react";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { MetricCard, DateRangePicker, getDefaultDateRange, DateRange } from "@/components/tracking/shared";
import { TaskSelect } from "@/components/tracking/TaskSelect";
import {
  useTrackerTimesheet,
  useTrackerQA,
  useUpdateTrackerEntry,
  TrackerTimesheetEntry,
} from "@/hooks/useTrackerTimesheet";

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

// Local-date YYYY-MM-DD (NOT toISOString, which converts to UTC and can shift
// the day by one for non-UTC users).
const toISO = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

function ConfidenceBadge({ score, label }: { score: number | null; label: (pct: number) => string }) {
  if (score == null) return null;
  const pct = Math.round(score * 100);
  const tone =
    pct >= 75
      ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
      : pct >= 50
      ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"
      : "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400";
  return <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${tone}`}>{label(pct)}</span>;
}

// One timesheet row with confirm / reassign / dismiss review actions.
function EntryRow({ entry }: { entry: TrackerTimesheetEntry }) {
  const t = useTranslations("tracking.tracker");
  const update = useUpdateTrackerEntry();
  const [reassigning, setReassigning] = useState(false);

  const status = entry.attribution_status;
  const reviewed = status === "confirmed" || status === "corrected";
  const busy = update.isPending;

  const act = (action: "confirm" | "dismiss") => update.mutate({ entryId: entry.id, action });
  const correct = (taskId: string) => {
    update.mutate({ entryId: entry.id, action: "correct", taskId });
    setReassigning(false);
  };

  return (
    <li className="flex items-center justify-between gap-3 py-2 text-sm">
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{entry.task_title || t("unattributed")}</div>
        {entry.description && (
          <div className="truncate text-xs text-gray-400">{entry.description}</div>
        )}
      </div>

      <ConfidenceBadge score={entry.confidence_score} label={(pct) => t("confidence", { pct })} />

      {status === "confirmed" && (
        <span className="rounded bg-green-100 px-1.5 py-0.5 text-xs font-medium text-green-700 dark:bg-green-900/30 dark:text-green-400">
          {t("statusConfirmed")}
        </span>
      )}
      {status === "corrected" && (
        <span className="rounded bg-blue-100 px-1.5 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
          {t("statusCorrected")}
        </span>
      )}

      {/* Review actions — only for not-yet-reviewed (inferred) entries. */}
      {!reviewed &&
        (reassigning ? (
          <TaskSelect value={entry.task_id} onSelect={correct} disabled={busy} />
        ) : (
          <div className="flex shrink-0 items-center gap-1">
            <button
              onClick={() => act("confirm")}
              disabled={busy}
              aria-label={t("confirm")}
              title={t("confirm")}
              className="rounded p-1 text-green-600 hover:bg-green-50 disabled:opacity-40 dark:hover:bg-green-900/20"
            >
              <Check className="h-4 w-4" />
            </button>
            <button
              onClick={() => setReassigning(true)}
              disabled={busy}
              aria-label={t("reassign")}
              title={t("reassign")}
              className="rounded p-1 text-gray-500 hover:bg-gray-100 disabled:opacity-40 dark:hover:bg-gray-800"
            >
              <Pencil className="h-4 w-4" />
            </button>
            <button
              onClick={() => act("dismiss")}
              disabled={busy}
              aria-label={t("dismiss")}
              title={t("dismiss")}
              className="rounded p-1 text-gray-500 hover:bg-red-50 hover:text-red-600 disabled:opacity-40 dark:hover:bg-red-900/20"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ))}

      <span className="shrink-0 tabular-nums text-gray-500">{fmtDuration(entry.duration_minutes)}</span>
    </li>
  );
}

export default function TrackerTimesheetPage() {
  const t = useTranslations("tracking.tracker");
  const [dateRange, setDateRange] = useState<DateRange>(getDefaultDateRange("this_week"));
  const range = { start: toISO(dateRange.startDate), end: toISO(dateRange.endDate) };
  const { data, isLoading } = useTrackerTimesheet(range);

  const [question, setQuestion] = useState("");
  const qa = useTrackerQA();

  // Q&A should cover the same window the user picked (clamped to the API's 1..90).
  const rangeDays = useMemo(
    () =>
      Math.min(
        90,
        Math.max(
          1,
          Math.round(
            (dateRange.endDate.getTime() - dateRange.startDate.getTime()) / 86_400_000,
          ) + 1,
        ),
      ),
    [dateRange],
  );

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
    qa.mutate({ question: text, days: rangeDays });
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
            {t("title")}
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">{t("subtitle")}</p>
        </div>
        <DateRangePicker value={dateRange} onChange={setDateRange} />
      </div>

      {/* Metrics */}
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard title={t("metricTotal")} value={fmtDuration(data?.total_minutes || 0)} icon={Clock} />
        <MetricCard title={t("metricDays")} value={stats.trackedDays} icon={CalendarDays} />
        <MetricCard title={t("metricEntries")} value={stats.totalEntries} icon={ListChecks} />
        <MetricCard title={t("metricAvg")} value={fmtDuration(stats.avg)} icon={Activity} />
      </div>

      {/* Ask AI */}
      <div className="mb-8 rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-900">
        <div className="mb-2 flex items-center gap-2 text-sm font-medium">
          <Sparkles className="h-4 w-4 text-purple-500" />
          {t("askTitle")}
        </div>
        <div className="flex gap-2">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && askQuestion()}
            placeholder={t("askPlaceholder")}
            aria-label={t("askAriaLabel")}
            className="flex-1 rounded-lg border border-gray-300 bg-transparent px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-gray-700"
          />
          <button
            onClick={() => askQuestion()}
            disabled={qa.isPending || !question.trim()}
            className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {qa.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            {t("ask")}
          </button>
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
          {[
            t("suggestStandup"),
            t("suggestShipped"),
            t("suggestWhereTime"),
          ].map((s) => (
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
              {t("basedOn", { journals: qa.data.journals_used, entries: qa.data.time_entries_used })}
            </div>
          </div>
        )}
        {qa.isError && (
          <div className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-600 dark:bg-red-900/20">
            {t("qaError")}
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
          {t("empty")}
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
                  <EntryRow key={e.id} entry={e} />
                ))}
                {!day.entries.length && (
                  <li className="py-2 text-xs text-gray-400">{t("journalOnly")}</li>
                )}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

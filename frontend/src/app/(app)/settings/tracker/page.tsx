"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Activity, Loader2, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { useWorkspace, useWorkspaceMembers } from "@/hooks/useWorkspace";
import {
  useWorkspaceTrackerProjects,
  useAdminTimesheet,
} from "@/hooks/useTrackerAdmin";

function fmtDuration(minutes: number) {
  if (!minutes) return "0m";
  if (minutes < 60) return `${Math.round(minutes)}m`;
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

const localISO = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export default function WorkspaceTrackerAdminPage() {
  const t = useTranslations("settings.tracker");
  const { currentWorkspace } = useWorkspace();
  const workspaceId = currentWorkspace?.id || null;

  const [tab, setTab] = useState<"projects" | "records">("projects");
  const projectsQuery = useWorkspaceTrackerProjects(workspaceId);

  const { members } = useWorkspaceMembers(workspaceId);
  const [developerId, setDeveloperId] = useState<string>("");

  const range = useMemo(() => {
    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - 6);
    return { start: localISO(start), end: localISO(end) };
  }, []);
  const timesheet = useAdminTimesheet(workspaceId, developerId || null, range);

  const tabBtn = (id: "projects" | "records", label: string) => (
    <button
      onClick={() => setTab(id)}
      className={
        tab === id
          ? "px-4 py-2 bg-primary-600 text-white rounded-lg text-sm font-medium"
          : "px-4 py-2 bg-muted hover:bg-accent text-foreground rounded-lg text-sm font-medium transition"
      }
    >
      {label}
    </button>
  );

  return (
    <div className="mx-auto max-w-4xl px-4 py-6">
      <Breadcrumb items={[{ label: "Settings", href: "/settings" }, { label: t("title") }]} className="mb-6" />

      <div className="mb-6">
        <h1 className="flex items-center gap-2 text-2xl font-semibold">
          <Activity className="h-6 w-6 text-blue-500" />
          {t("title")}
        </h1>
        <p className="text-sm text-gray-500 dark:text-gray-400">{t("adminSubtitle")}</p>
      </div>

      <div className="mb-6 flex gap-2">
        {tabBtn("projects", t("tabProjects"))}
        {tabBtn("records", t("tabRecords"))}
      </div>

      {tab === "projects" ? (
        projectsQuery.isLoading ? (
          <div className="flex justify-center py-16 text-gray-400">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        ) : projectsQuery.isError ? (
          <div className="rounded-xl border border-dashed border-gray-300 py-16 text-center text-gray-500 dark:border-gray-700">
            {t("adminAccessDenied")}
          </div>
        ) : !projectsQuery.data?.length ? (
          <div className="rounded-xl border border-dashed border-gray-300 py-16 text-center text-gray-500 dark:border-gray-700">
            {t("noProjects")}
          </div>
        ) : (
          <ul className="divide-y divide-gray-100 rounded-xl border border-gray-200 dark:divide-gray-800 dark:border-gray-800">
            {projectsQuery.data.map((p) => (
              <li key={p.id} className="flex items-center justify-between gap-3 p-4">
                <div className="min-w-0">
                  <div className="truncate font-medium">{p.name}</div>
                  <div className="text-xs text-gray-500">
                    {t("devicesCount", { count: p.device_count })} · {t("activeCount", { count: p.active_devices })}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span
                    className={
                      p.enabled
                        ? "rounded px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                        : "rounded px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400"
                    }
                  >
                    {p.enabled ? t("enabled") : t("disabled")}
                  </span>
                  <Link
                    href={`/settings/projects/${p.id}/tracker`}
                    className="flex items-center gap-1 text-sm text-blue-600 hover:underline"
                  >
                    {t("configure")}
                    <ChevronRight className="h-4 w-4" />
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        )
      ) : (
        <div className="space-y-4">
          <div>
            <h2 className="font-medium">{t("recordsTitle")}</h2>
            <p className="text-sm text-gray-500">{t("recordsSubtitle")}</p>
          </div>
          <select
            value={developerId}
            onChange={(e) => setDeveloperId(e.target.value)}
            className="rounded-lg border border-gray-300 bg-transparent px-3 py-2 text-sm dark:border-gray-700"
          >
            <option value="">{t("selectDeveloper")}</option>
            {(members as Array<{ developer_id: string; name?: string; email?: string }> | undefined)?.map((m) => (
              <option key={m.developer_id} value={m.developer_id}>
                {m.name || m.email || m.developer_id}
              </option>
            ))}
          </select>

          {developerId &&
            (timesheet.isLoading ? (
              <div className="flex justify-center py-12 text-gray-400">
                <Loader2 className="h-6 w-6 animate-spin" />
              </div>
            ) : timesheet.isError ? (
              <div className="rounded-lg bg-red-50 p-3 text-sm text-red-600 dark:bg-red-900/20">
                {t("noRecordsPermission")}
              </div>
            ) : !timesheet.data?.days?.length ? (
              <div className="rounded-xl border border-dashed border-gray-300 py-12 text-center text-gray-500 dark:border-gray-700">
                {t("noActivity")}
              </div>
            ) : (
              <div className="space-y-3">
                <div className="text-sm text-gray-500">
                  {t("totalTracked")}: {fmtDuration(timesheet.data.total_minutes)}
                </div>
                {timesheet.data.days.map((day) => (
                  <div
                    key={day.date}
                    className="rounded-xl border border-gray-200 bg-card p-4 dark:border-gray-800"
                  >
                    <div className="mb-2 flex items-center justify-between">
                      <span className="font-medium">{day.date}</span>
                      <span className="text-sm text-gray-500">{fmtDuration(day.total_minutes)}</span>
                    </div>
                    {day.journal && (
                      <p className="mb-2 border-l-2 border-blue-400 pl-3 text-sm italic text-gray-600 dark:text-gray-300">
                        {day.journal}
                      </p>
                    )}
                    <ul className="divide-y divide-gray-100 text-sm dark:divide-gray-800">
                      {day.entries.map((e) => (
                        <li key={e.id} className="flex items-center justify-between gap-3 py-2">
                          <span className="truncate">{e.task_title || e.description || "—"}</span>
                          <span className="shrink-0 tabular-nums text-gray-500">
                            {fmtDuration(e.duration_minutes)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { sprintApi } from "@/lib/api";

/**
 * Manual link-picker for attaching GitHub pull requests / issues to a task.
 *
 * Rendering of the linked list lives in the EditTaskModal's "GitHub activity"
 * section (the single links UI), which fetches under the query key
 * ["taskGithubLinks", sprintId, teamId, taskId]. This component only adds
 * links and invalidates that same key so the list refreshes in place.
 */
export function TaskGitHubLinksSection({
  sprintId,
  teamId,
  taskId,
}: {
  sprintId: string;
  teamId?: string | null;
  taskId: string;
}) {
  const t = useTranslations("sprints.githubLinks");
  const qc = useQueryClient();
  const [showLink, setShowLink] = useState(false);

  // Must match EditTaskModal's githubLinksQueryKey exactly — it owns the list.
  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["taskGithubLinks", sprintId, teamId, taskId] });

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
          GitHub
        </label>
        <button
          type="button"
          onClick={() => setShowLink((v) => !v)}
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <Plus className="h-3 w-3" /> {t("link")}
        </button>
      </div>

      {showLink && (
        <LinkForm
          sprintId={sprintId}
          taskId={taskId}
          onLinked={() => {
            invalidate();
            setShowLink(false);
          }}
        />
      )}
    </div>
  );
}

function LinkForm({
  sprintId,
  taskId,
  onLinked,
}: {
  sprintId: string;
  taskId: string;
  onLinked: () => void;
}) {
  const t = useTranslations("sprints.githubLinks");
  const [prId, setPrId] = useState("");
  const [issueRepo, setIssueRepo] = useState("");
  const [issueNumber, setIssueNumber] = useState("");

  const { data: prs = [] } = useQuery({
    queryKey: ["linkablePRs", sprintId],
    queryFn: () => sprintApi.listLinkablePullRequests(sprintId),
    enabled: !!sprintId,
  });
  const { data: repos = [] } = useQuery({
    queryKey: ["issueRepos", sprintId, taskId],
    queryFn: () => sprintApi.listIssueRepositories(sprintId, taskId),
    enabled: !!sprintId && !!taskId,
  });

  const linkPr = useMutation({
    mutationFn: (id: string) => sprintApi.linkGitHubPullRequest(sprintId, taskId, id),
    onSuccess: onLinked,
  });
  const linkIssue = useMutation({
    mutationFn: (data: { repository: string; issue_number: number }) =>
      sprintApi.linkGitHubIssue(sprintId, taskId, data),
    onSuccess: onLinked,
  });

  const inputCls =
    "w-full px-2 py-1.5 bg-background/50 border border-border rounded text-sm text-foreground focus:outline-none focus:border-primary-500";

  return (
    <div className="mt-2 p-2 border border-border rounded space-y-3 bg-muted/30">
      {/* Link a pull request */}
      <div className="flex items-center gap-2">
        <select value={prId} onChange={(e) => setPrId(e.target.value)} className={inputCls}>
          <option value="">{t("linkPullRequestPlaceholder")}</option>
          {prs.map((pr) => (
            <option key={pr.id} value={pr.id}>
              #{pr.number} {pr.title}
            </option>
          ))}
        </select>
        <button
          type="button"
          disabled={!prId || linkPr.isPending}
          onClick={() => linkPr.mutate(prId)}
          className="px-2 py-1.5 text-xs bg-primary-600 text-white rounded disabled:opacity-50 shrink-0"
        >
          {t("link")}
        </button>
      </div>

      {/* Link an issue */}
      <div className="flex items-center gap-2">
        {repos.length > 0 ? (
          <select value={issueRepo} onChange={(e) => setIssueRepo(e.target.value)} className={inputCls}>
            <option value="">{t("repositoryPlaceholder")}</option>
            {repos.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        ) : (
          <input
            aria-label={t("issueRepositoryAriaLabel")}
            placeholder={t("ownerRepoPlaceholder")}
            value={issueRepo}
            onChange={(e) => setIssueRepo(e.target.value)}
            className={inputCls}
          />
        )}
        <input
          aria-label={t("issueNumberAriaLabel")}
          placeholder="#"
          value={issueNumber}
          onChange={(e) => setIssueNumber(e.target.value)}
          className="w-20 px-2 py-1.5 bg-background/50 border border-border rounded text-sm text-foreground focus:outline-none focus:border-primary-500 shrink-0"
        />
        <button
          type="button"
          disabled={!issueRepo || !issueNumber || linkIssue.isPending}
          onClick={() =>
            linkIssue.mutate({ repository: issueRepo, issue_number: Number(issueNumber) })
          }
          className="px-2 py-1.5 text-xs bg-primary-600 text-white rounded disabled:opacity-50 shrink-0"
        >
          {t("link")}
        </button>
      </div>
    </div>
  );
}

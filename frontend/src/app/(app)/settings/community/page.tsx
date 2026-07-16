"use client";

import { useCallback, useEffect, useState } from "react";
import { Globe, Loader2, ExternalLink, ShieldAlert, Check, X } from "lucide-react";
import { useWorkspace } from "@/hooks/useWorkspace";
import { communityApi, CommunitySettings, MemberPublicPref } from "@/lib/api";
import { toast } from "sonner";

interface PendingPost {
  id: string;
  content: string;
  created_at: string;
  channel_name: string;
  topic_name: string;
  sender_id: string;
}

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "https://aexy.io";

export default function CommunitySettingsPage() {
  const { currentWorkspace } = useWorkspace();
  const workspaceId = currentWorkspace?.id;

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [settings, setSettings] = useState<CommunitySettings | null>(null);
  const [pref, setPref] = useState<MemberPublicPref>({
    public_display: "name",
    public_alias: null,
  });
  const [pending, setPending] = useState<PendingPost[]>([]);

  const loadPending = useCallback(async () => {
    if (!workspaceId) return;
    try {
      const res = await communityApi.listModerationQueue(workspaceId);
      setPending(res.pending);
    } catch {
      /* non-admins / disabled — ignore */
    }
  }, [workspaceId]);

  useEffect(() => {
    if (!workspaceId) return;
    (async () => {
      setLoading(true);
      try {
        const [s, p] = await Promise.allSettled([
          communityApi.getSettings(workspaceId),
          communityApi.getMyPref(workspaceId),
        ]);
        if (s.status === "fulfilled") setSettings(s.value);
        else
          setSettings({
            workspace_id: workspaceId,
            enabled: false,
            community_slug: currentWorkspace?.slug || "",
            title: null,
            description: null,
            logo_url: null,
            theme: {},
            default_public_display: "name",
            noindex: false,
            listed: false,
            allow_participation: false,
            post_moderation: "post",
          });
        if (p.status === "fulfilled") setPref(p.value);
        await loadPending();
      } finally {
        setLoading(false);
      }
    })();
  }, [workspaceId, currentWorkspace?.slug, loadPending]);

  const moderate = async (id: string, action: "approve" | "reject") => {
    if (!workspaceId) return;
    try {
      if (action === "approve") await communityApi.approvePost(workspaceId, id);
      else await communityApi.rejectPost(workspaceId, id);
      setPending((prev) => prev.filter((p) => p.id !== id));
      toast.success(action === "approve" ? "Post approved" : "Post rejected");
    } catch {
      toast.error("Could not update the post");
    }
  };

  const saveSettings = async (patch: Partial<CommunitySettings>) => {
    if (!workspaceId || !settings) return;
    setSaving(true);
    try {
      const updated = await communityApi.updateSettings(workspaceId, {
        ...patch,
      });
      setSettings(updated);
      toast.success("Community settings saved");
    } catch (e) {
      toast.error("Could not save settings (admin required?)");
    } finally {
      setSaving(false);
    }
  };

  const savePref = async (next: MemberPublicPref) => {
    if (!workspaceId) return;
    setPref(next);
    try {
      await communityApi.setMyPref(workspaceId, next);
    } catch {
      toast.error("Could not save your display preference");
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    );
  }

  const publicUrl = settings
    ? `${SITE_URL}/community/${settings.community_slug}`
    : "";

  return (
    <div className="max-w-2xl space-y-8">
      <div className="flex items-center gap-3">
        <Globe className="h-6 w-6 text-blue-600" />
        <div>
          <h1 className="text-xl font-bold text-gray-900 dark:text-white">
            Public community
          </h1>
          <p className="text-sm text-gray-500">
            Publish selected chat channels as a public, SEO-friendly forum.
          </p>
        </div>
      </div>

      {/* Master switch */}
      <section className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 space-y-4">
        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            className="mt-1"
            checked={settings?.enabled ?? false}
            disabled={saving}
            onChange={(e) => saveSettings({ enabled: e.target.checked })}
          />
          <span>
            <span className="font-medium text-gray-900 dark:text-white">
              Enable public community
            </span>
            <p className="text-sm text-gray-500">
              Master switch. While off, nothing is visible to the public even if
              individual channels are marked public.
            </p>
          </span>
        </label>

        {settings?.enabled && (
          <div className="rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 p-3 flex gap-2 text-sm text-amber-800 dark:text-amber-300">
            <ShieldAlert className="h-4 w-4 mt-0.5 shrink-0" />
            <span>
              Channels you mark <strong>web public</strong> — and their history
              from the moment you publish — become visible to anyone on the
              internet and may be indexed by search engines.
            </span>
          </div>
        )}
      </section>

      {/* Branding + URL */}
      <section className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 space-y-4">
        <h2 className="font-semibold text-gray-900 dark:text-white">Forum details</h2>

        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Public URL
          </label>
          <div className="flex items-center gap-2">
            <code className="text-sm text-gray-600 dark:text-gray-400 truncate">
              {publicUrl}
            </code>
            {settings?.enabled && (
              <a
                href={publicUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 hover:text-blue-700"
              >
                <ExternalLink className="h-4 w-4" />
              </a>
            )}
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Title
          </label>
          <input
            type="text"
            defaultValue={settings?.title || ""}
            onBlur={(e) => saveSettings({ title: e.target.value })}
            className="w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-transparent px-3 py-2 text-sm"
            placeholder="Acme Community"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Description
          </label>
          <textarea
            defaultValue={settings?.description || ""}
            onBlur={(e) => saveSettings({ description: e.target.value })}
            className="w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-transparent px-3 py-2 text-sm"
            rows={3}
            placeholder="What this community is about (used as the meta description)."
          />
        </div>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={settings?.noindex ?? false}
            disabled={saving}
            onChange={(e) => saveSettings({ noindex: e.target.checked })}
          />
          <span className="text-gray-700 dark:text-gray-300">
            Public but <strong>not</strong> indexed by search engines (noindex)
          </span>
        </label>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={settings?.listed ?? false}
            disabled={saving}
            onChange={(e) => saveSettings({ listed: e.target.checked })}
          />
          <span className="text-gray-700 dark:text-gray-300">
            List this community in the public directory at{" "}
            <code>/community</code>
          </span>
        </label>
      </section>

      {/* Participation + moderation */}
      <section className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 space-y-4">
        <h2 className="font-semibold text-gray-900 dark:text-white">Participation</h2>
        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            className="mt-1"
            checked={settings?.allow_participation ?? false}
            disabled={saving}
            onChange={(e) => saveSettings({ allow_participation: e.target.checked })}
          />
          <span>
            <span className="font-medium text-gray-900 dark:text-white">
              Let signed-in visitors reply
            </span>
            <p className="text-sm text-gray-500">
              Anyone signed in to Aexy can post in public channels. When off, the
              forum is read-only.
            </p>
          </span>
        </label>

        {settings?.allow_participation && (
          <div className="pl-7 space-y-2">
            <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
              How new replies are handled
            </p>
            {[
              { value: "post", label: "Publish immediately (moderate afterwards)" },
              { value: "pre", label: "Hold for my approval before publishing" },
            ].map((opt) => (
              <label key={opt.value} className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="post_moderation"
                  checked={(settings?.post_moderation || "post") === opt.value}
                  onChange={() => saveSettings({ post_moderation: opt.value })}
                />
                <span className="text-gray-700 dark:text-gray-300">{opt.label}</span>
              </label>
            ))}
          </div>
        )}
      </section>

      {/* Moderation queue */}
      {pending.length > 0 && (
        <section
          data-testid="moderation-queue"
          className="rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-900/10 p-5 space-y-3"
        >
          <h2 className="font-semibold text-gray-900 dark:text-white">
            Pending review ({pending.length})
          </h2>
          <ul className="space-y-2">
            {pending.map((p) => (
              <li
                key={p.id}
                className="flex items-start justify-between gap-3 rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-3"
              >
                <div className="min-w-0">
                  <p className="text-xs text-gray-400">
                    #{p.channel_name} · {p.topic_name}
                  </p>
                  <p className="text-sm text-gray-800 dark:text-gray-200 break-words">
                    {p.content}
                  </p>
                </div>
                <div className="flex gap-1 shrink-0">
                  <button
                    onClick={() => moderate(p.id, "approve")}
                    className="rounded-lg bg-green-600 p-1.5 text-white hover:bg-green-700"
                    title="Approve"
                  >
                    <Check className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => moderate(p.id, "reject")}
                    className="rounded-lg bg-red-600 p-1.5 text-white hover:bg-red-700"
                    title="Reject"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Per-member display preference */}
      <section className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 space-y-3">
        <h2 className="font-semibold text-gray-900 dark:text-white">
          How you appear publicly
        </h2>
        <p className="text-sm text-gray-500">
          Controls the name shown next to your messages on public pages.
        </p>
        <div className="space-y-2">
          {[
            { value: "name", label: "My real name" },
            { value: "alias", label: "An alias" },
            { value: "anonymous", label: "Anonymous (“Community member”)" },
          ].map((opt) => (
            <label key={opt.value} className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="public_display"
                checked={pref.public_display === opt.value}
                onChange={() =>
                  savePref({ ...pref, public_display: opt.value })
                }
              />
              <span className="text-gray-700 dark:text-gray-300">{opt.label}</span>
            </label>
          ))}
          {pref.public_display === "alias" && (
            <input
              type="text"
              defaultValue={pref.public_alias || ""}
              onBlur={(e) =>
                savePref({ ...pref, public_alias: e.target.value })
              }
              className="w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-transparent px-3 py-2 text-sm"
              placeholder="Your public alias"
            />
          )}
        </div>
      </section>
    </div>
  );
}

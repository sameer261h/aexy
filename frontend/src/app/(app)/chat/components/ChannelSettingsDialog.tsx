"use client";

import { useEffect, useState } from "react";
import { X, Globe, Hash, Lock, ExternalLink } from "lucide-react";
import { useUpdateChannel } from "@/hooks/useChat";
import { communityApi, ChatChannel, CommunitySettings } from "@/lib/api";
import { toast } from "sonner";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://aexy.io";

type Vis = "private" | "workspace" | "web_public";

const OPTIONS: { value: Vis; label: string; hint: string; icon: typeof Hash }[] = [
  { value: "private", label: "Private", hint: "Only invited channel members.", icon: Lock },
  { value: "workspace", label: "Workspace", hint: "Any member of this workspace.", icon: Hash },
  {
    value: "web_public",
    label: "Public on the web",
    hint: "Anyone on the internet; indexable by search engines.",
    icon: Globe,
  },
];

/**
 * Per-channel visibility control. Publishing a channel to the web is workspace-
 * admin-gated server-side (the PATCH returns 403 otherwise); we surface that as
 * a toast rather than pre-computing the role client-side.
 */
export function ChannelSettingsDialog({
  workspaceId,
  channel,
  open,
  onClose,
}: {
  workspaceId: string;
  channel: ChatChannel;
  open: boolean;
  onClose: () => void;
}) {
  const updateChannel = useUpdateChannel(workspaceId);
  const [community, setCommunity] = useState<CommunitySettings | null>(null);

  const normalized: Vis =
    channel.visibility === "public" ? "workspace" : (channel.visibility as Vis);

  useEffect(() => {
    if (!open) return;
    communityApi
      .getSettings(workspaceId)
      .then(setCommunity)
      .catch(() => setCommunity(null)); // 404 = community not configured yet
  }, [open, workspaceId]);

  if (!open) return null;

  const applyVisibility = async (value: Vis) => {
    if (value === normalized) return;
    try {
      await updateChannel.mutateAsync({ channelId: channel.id, data: { visibility: value } });
      toast.success(
        value === "web_public"
          ? "Channel published to the web"
          : "Channel visibility updated",
      );
      if (value === "web_public" && !community?.enabled) {
        toast.message("Enable the community in Settings → Public Community for it to appear.");
      }
    } catch (e: unknown) {
      const status = (e as { response?: { status?: number } })?.response?.status;
      if (status === 403) toast.error("Only a workspace admin can publish a channel to the web.");
      else toast.error("Could not update visibility.");
    }
  };

  const forumUrl =
    community?.community_slug && normalized === "web_public"
      ? `${SITE_URL}/community/${community.community_slug}/${channel.slug}`
      : null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="bg-card border border-border rounded-xl w-full max-w-md p-6 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold truncate">#{channel.name} · Settings</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-accent">
            <X className="h-4 w-4" />
          </button>
        </div>

        <p className="text-sm font-medium mb-2">Visibility</p>
        <div className="space-y-2">
          {OPTIONS.map((opt) => {
            const Icon = opt.icon;
            const active = normalized === opt.value;
            return (
              <button
                key={opt.value}
                disabled={updateChannel.isPending}
                onClick={() => applyVisibility(opt.value)}
                className={`w-full flex items-start gap-3 rounded-lg border p-3 text-left transition-colors disabled:opacity-50 ${
                  active
                    ? "border-primary bg-primary/5"
                    : "border-border hover:bg-accent/50"
                }`}
              >
                <Icon className={`h-4 w-4 mt-0.5 shrink-0 ${active ? "text-primary" : "text-muted-foreground"}`} />
                <span>
                  <span className="block text-sm font-medium">{opt.label}</span>
                  <span className="block text-xs text-muted-foreground">{opt.hint}</span>
                </span>
              </button>
            );
          })}
        </div>

        {normalized === "web_public" && (
          <p className="mt-3 text-xs text-muted-foreground">
            New messages here are visible to anyone and may be indexed. History
            before publishing stays private unless full backfill is enabled.
          </p>
        )}

        {forumUrl && (
          <a
            href={forumUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-4 inline-flex items-center gap-1.5 text-sm text-blue-600 hover:underline"
          >
            View public forum <ExternalLink className="h-3.5 w-3.5" />
          </a>
        )}
      </div>
    </div>
  );
}

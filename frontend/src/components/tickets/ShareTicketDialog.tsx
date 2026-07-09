"use client";

import { useEffect, useState } from "react";
import {
  X,
  Copy,
  Check,
  Loader2,
  RefreshCw,
  Trash2,
  Globe,
} from "lucide-react";
import { ticketsApi, TicketShareLink } from "@/lib/api";

interface ShareTicketDialogProps {
  workspaceId: string;
  ticketId: string;
  ticketNumber: number;
  onClose: () => void;
}

export function ShareTicketDialog({
  workspaceId,
  ticketId,
  ticketNumber,
  onClose,
}: ShareTicketDialogProps) {
  const [link, setLink] = useState<TicketShareLink | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Optional restrictions
  const [password, setPassword] = useState("");
  const [expiresAt, setExpiresAt] = useState("");

  useEffect(() => {
    let active = true;
    ticketsApi
      .getShare(workspaceId, ticketId)
      .then((l) => {
        if (active) setLink(l);
      })
      .catch(() => {
        if (active) setError("Failed to load sharing settings");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [workspaceId, ticketId]);

  const enable = async () => {
    setWorking(true);
    setError(null);
    try {
      const l = await ticketsApi.createShare(workspaceId, ticketId, {
        password: password || undefined,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : undefined,
      });
      setLink(l);
    } catch {
      setError("Failed to create share link");
    } finally {
      setWorking(false);
    }
  };

  const toggleActive = async (isActive: boolean) => {
    setWorking(true);
    setError(null);
    try {
      const l = await ticketsApi.updateShare(workspaceId, ticketId, {
        is_active: isActive,
      });
      setLink(l);
    } catch {
      setError("Failed to update share link");
    } finally {
      setWorking(false);
    }
  };

  const regenerate = async () => {
    setWorking(true);
    setError(null);
    try {
      const l = await ticketsApi.updateShare(workspaceId, ticketId, {
        regenerate: true,
      });
      setLink(l);
    } catch {
      setError("Failed to regenerate link");
    } finally {
      setWorking(false);
    }
  };

  const revoke = async () => {
    setWorking(true);
    setError(null);
    try {
      await ticketsApi.revokeShare(workspaceId, ticketId);
      setLink(null);
      setPassword("");
      setExpiresAt("");
    } catch {
      setError("Failed to revoke link");
    } finally {
      setWorking(false);
    }
  };

  const copy = async () => {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link.url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard unavailable — user can select manually */
    }
  };

  const isShared = !!link && link.is_active;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-lg bg-background rounded-xl border border-border shadow-xl">
        <div className="flex items-center justify-between border-b border-border p-5">
          <h3 className="flex items-center gap-2 text-lg font-semibold text-foreground">
            <Globe className="h-5 w-5 text-purple-400" />
            Share ticket TKT-{ticketNumber}
          </h3>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground transition"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {loading ? (
            <div className="flex items-center justify-center py-8 text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : (
            <>
              <p className="text-sm text-muted-foreground">
                Anyone with this link can view a read-only version of this
                ticket without signing in. Internal notes stay private.
              </p>

              {error && (
                <div className="rounded-lg bg-red-50 dark:bg-red-900/30 px-3 py-2 text-sm text-red-600 dark:text-red-400">
                  {error}
                </div>
              )}

              {isShared ? (
                <>
                  <div className="flex items-center gap-2">
                    <input
                      readOnly
                      value={link!.url}
                      className="flex-1 rounded-lg border border-border bg-muted px-3 py-2 text-sm text-foreground"
                      onFocus={(e) => e.target.select()}
                    />
                    <button
                      onClick={copy}
                      className="flex items-center gap-1.5 rounded-lg bg-purple-600 px-3 py-2 text-sm text-white hover:bg-purple-500 transition"
                    >
                      {copied ? (
                        <Check className="h-4 w-4" />
                      ) : (
                        <Copy className="h-4 w-4" />
                      )}
                      {copied ? "Copied" : "Copy"}
                    </button>
                  </div>

                  <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                    <span>{link!.use_count} view(s)</span>
                    {link!.has_password && <span>· Password protected</span>}
                    {link!.expires_at && (
                      <span>
                        · Expires{" "}
                        {new Date(link!.expires_at).toLocaleDateString()}
                      </span>
                    )}
                  </div>

                  <div className="flex flex-wrap gap-2 pt-2">
                    <button
                      onClick={regenerate}
                      disabled={working}
                      className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-foreground hover:bg-muted transition disabled:opacity-50"
                    >
                      <RefreshCw className="h-4 w-4" />
                      Regenerate
                    </button>
                    <button
                      onClick={() => toggleActive(false)}
                      disabled={working}
                      className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-foreground hover:bg-muted transition disabled:opacity-50"
                    >
                      Disable
                    </button>
                    <button
                      onClick={revoke}
                      disabled={working}
                      className="flex items-center gap-1.5 rounded-lg border border-red-300 dark:border-red-900 px-3 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30 transition disabled:opacity-50"
                    >
                      <Trash2 className="h-4 w-4" />
                      Revoke
                    </button>
                  </div>
                </>
              ) : link && !link.is_active ? (
                <button
                  onClick={() => toggleActive(true)}
                  disabled={working}
                  className="flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm text-white hover:bg-purple-500 transition disabled:opacity-50"
                >
                  {working && <Loader2 className="h-4 w-4 animate-spin" />}
                  Re-enable sharing
                </button>
              ) : (
                <>
                  <div className="space-y-3">
                    <div>
                      <label className="mb-1 block text-sm font-medium text-muted-foreground">
                        Password (optional)
                      </label>
                      <input
                        type="text"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        placeholder="Leave empty for no password"
                        className="w-full rounded-lg border border-border bg-muted px-3 py-2 text-sm text-foreground"
                      />
                    </div>
                    <div>
                      <label className="mb-1 block text-sm font-medium text-muted-foreground">
                        Expires (optional)
                      </label>
                      <input
                        type="date"
                        value={expiresAt}
                        onChange={(e) => setExpiresAt(e.target.value)}
                        className="w-full rounded-lg border border-border bg-muted px-3 py-2 text-sm text-foreground"
                      />
                    </div>
                  </div>
                  <button
                    onClick={enable}
                    disabled={working}
                    className="flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm text-white hover:bg-purple-500 transition disabled:opacity-50"
                  >
                    {working && <Loader2 className="h-4 w-4 animate-spin" />}
                    Create public link
                  </button>
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

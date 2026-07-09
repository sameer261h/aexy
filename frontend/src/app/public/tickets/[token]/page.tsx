"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  Loader2,
  AlertCircle,
  Lock,
  MessageSquare,
  Send,
  CheckCircle2,
  Clock,
  Paperclip,
  Download,
} from "lucide-react";
import {
  publicTicketsApi,
  PublicTicketView,
  PublicTicketComment,
  TicketAttachment,
} from "@/lib/api";

const STATUS_LABELS: Record<string, string> = {
  new: "New",
  acknowledged: "Acknowledged",
  in_progress: "In Progress",
  waiting_on_submitter: "Waiting on Submitter",
  resolved: "Resolved",
  closed: "Closed",
};

const STATUS_STYLES: Record<string, string> = {
  new: "bg-blue-100 text-blue-700",
  acknowledged: "bg-purple-100 text-purple-700",
  in_progress: "bg-yellow-100 text-yellow-700",
  waiting_on_submitter: "bg-orange-100 text-orange-700",
  resolved: "bg-green-100 text-green-700",
  closed: "bg-gray-200 text-gray-600",
};

function formatDate(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function formatBytes(bytes: number): string {
  if (!bytes || bytes < 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  let size = bytes;
  let i = 0;
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024;
    i++;
  }
  return `${size.toFixed(size < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

const IMAGE_EXT = /\.(png|jpe?g|gif|webp|svg|bmp)$/i;

function isImage(a: TicketAttachment): boolean {
  return (a.type?.startsWith("image/") ?? false) || IMAGE_EXT.test(a.filename || "");
}

function AttachmentList({
  attachments,
  urlFor,
}: {
  attachments: TicketAttachment[];
  urlFor?: (a: TicketAttachment) => string;
}) {
  if (!attachments || attachments.length === 0) return null;
  const getUrl = (a: TicketAttachment) => (urlFor ? urlFor(a) : a.url) || "";
  return (
    <div className="flex flex-wrap gap-3">
      {attachments.map((a, i) =>
        isImage(a) ? (
          <a
            key={a.id || i}
            href={getUrl(a)}
            target="_blank"
            rel="noopener noreferrer"
            className="group block overflow-hidden rounded-lg border border-gray-200"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={getUrl(a)}
              alt={a.filename}
              className="h-28 w-28 object-cover transition group-hover:opacity-90"
            />
          </a>
        ) : (
          <a
            key={a.id || i}
            href={getUrl(a)}
            target="_blank"
            rel="noopener noreferrer"
            download
            className="flex items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700 transition hover:bg-gray-100"
          >
            <Paperclip className="h-4 w-4 text-gray-400" />
            <span className="max-w-[12rem] truncate">{a.filename || "Attachment"}</span>
            {a.size ? (
              <span className="text-xs text-gray-400">{formatBytes(a.size)}</span>
            ) : null}
            <Download className="h-4 w-4 text-gray-400" />
          </a>
        )
      )}
    </div>
  );
}

function fieldLabel(ticket: PublicTicketView, key: string): string {
  const field = ticket.fields.find((f) => f.field_key === key);
  if (field?.name) return field.name;
  return key.replace(/_/g, " ");
}

function toAttachment(v: unknown): TicketAttachment | null {
  if (v && typeof v === "object" && "url" in (v as Record<string, unknown>)) {
    const o = v as Record<string, unknown>;
    return {
      filename: String(o.filename ?? o.name ?? "Attachment"),
      url: String(o.url),
      size: Number(o.size ?? 0),
      type: String(o.type ?? ""),
    };
  }
  return null;
}

function renderValue(value: unknown) {
  if (value == null || value === "") return <span className="text-gray-400">—</span>;

  if (Array.isArray(value)) {
    // A list of file objects renders as attachments; otherwise as chips.
    const files = value.map(toAttachment).filter((a): a is TicketAttachment => a !== null);
    if (files.length === value.length && files.length > 0) {
      return <AttachmentList attachments={files} />;
    }
    return (
      <div className="flex flex-wrap gap-2">
        {value.map((v, i) => (
          <span key={i} className="rounded bg-gray-100 px-2 py-0.5 text-sm text-gray-700">
            {String(v)}
          </span>
        ))}
      </div>
    );
  }

  const file = toAttachment(value);
  if (file) return <AttachmentList attachments={[file]} />;

  return <p className="whitespace-pre-wrap text-gray-900">{String(value)}</p>;
}

export default function PublicTicketPage() {
  const params = useParams();
  const token = params.token as string;

  const [ticket, setTicket] = useState<PublicTicketView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [needsPassword, setNeedsPassword] = useState(false);
  const [passwordInput, setPasswordInput] = useState("");
  const [password, setPassword] = useState<string | undefined>();

  // Reply state (only for authenticated workspace members)
  const [reply, setReply] = useState("");
  const [sendingReply, setSendingReply] = useState(false);
  const [replyError, setReplyError] = useState<string | null>(null);

  const load = useCallback(
    async (pwd?: string) => {
      setLoading(true);
      setError(null);
      try {
        const data = await publicTicketsApi.get(token, pwd);
        setTicket(data);
        setNeedsPassword(false);
        setPassword(pwd);
      } catch (err: any) {
        const status = err?.response?.status;
        const detail = err?.response?.data?.detail;
        if (status === 401 && (detail === "password_required" || detail === "invalid_password")) {
          setNeedsPassword(true);
          if (detail === "invalid_password") setError("Incorrect password. Please try again.");
        } else if (status === 404) {
          setError("This ticket link is invalid or no longer exists.");
        } else if (status === 410) {
          setError("This link has expired or is no longer available.");
        } else {
          setError("Something went wrong loading this ticket.");
        }
      } finally {
        setLoading(false);
      }
    },
    [token]
  );

  useEffect(() => {
    if (token) load();
  }, [token, load]);

  const submitPassword = (e: React.FormEvent) => {
    e.preventDefault();
    if (passwordInput.trim()) load(passwordInput.trim());
  };

  const submitReply = async () => {
    if (!reply.trim()) return;
    setSendingReply(true);
    setReplyError(null);
    try {
      const created: PublicTicketComment = await publicTicketsApi.reply(
        token,
        reply.trim(),
        password
      );
      setTicket((prev) =>
        prev ? { ...prev, responses: [...prev.responses, created] } : prev
      );
      setReply("");
    } catch {
      setReplyError("Failed to post reply. Please try again.");
    } finally {
      setSendingReply(false);
    }
  };

  // ---- Loading ----
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <Loader2 className="h-6 w-6 animate-spin text-purple-600" />
      </div>
    );
  }

  // ---- Password gate ----
  if (needsPassword) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
        <form
          onSubmit={submitPassword}
          className="w-full max-w-sm rounded-xl border border-gray-200 bg-white p-6 shadow-sm"
        >
          <div className="mb-4 flex items-center gap-2 text-gray-900">
            <Lock className="h-5 w-5 text-purple-600" />
            <h1 className="text-lg font-semibold">Password required</h1>
          </div>
          <p className="mb-4 text-sm text-gray-500">
            This ticket is protected. Enter the password to view it.
          </p>
          {error && (
            <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">
              {error}
            </div>
          )}
          <input
            type="password"
            value={passwordInput}
            onChange={(e) => setPasswordInput(e.target.value)}
            placeholder="Password"
            autoFocus
            className="mb-3 w-full rounded-lg border border-gray-200 px-3 py-2 text-gray-900 focus:border-transparent focus:outline-none focus:ring-2 focus:ring-purple-500"
          />
          <button
            type="submit"
            className="w-full rounded-lg bg-purple-600 px-4 py-2 text-white transition hover:bg-purple-500"
          >
            View ticket
          </button>
        </form>
      </div>
    );
  }

  // ---- Error ----
  if (error || !ticket) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
        <div className="max-w-sm text-center">
          <AlertCircle className="mx-auto mb-3 h-10 w-10 text-gray-400" />
          <p className="text-gray-600">{error || "Ticket not found."}</p>
        </div>
      </div>
    );
  }

  // ---- Ticket view ----
  return (
    <div className="min-h-screen bg-gray-50 py-10">
      <div className="mx-auto max-w-3xl px-4">
        {/* Header */}
        <div className="mb-4 rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <div className="mb-3 flex items-start justify-between gap-4">
            <div>
              <span className="font-mono text-sm text-purple-600">
                TKT-{ticket.ticket_number}
              </span>
              <h1 className="mt-1 text-2xl font-bold text-gray-900">
                {ticket.subject || ticket.form_name || "Ticket"}
              </h1>
            </div>
            <span
              className={`rounded-full px-3 py-1 text-sm font-medium ${
                STATUS_STYLES[ticket.status] || "bg-gray-100 text-gray-700"
              }`}
            >
              {STATUS_LABELS[ticket.status] || ticket.status}
            </span>
          </div>
          <div className="flex flex-wrap gap-4 text-sm text-gray-500">
            {ticket.submitter_name && <span>By {ticket.submitter_name}</span>}
            <span className="flex items-center gap-1">
              <Clock className="h-4 w-4" />
              {formatDate(ticket.created_at)}
            </span>
            {ticket.workspace_name && <span>· {ticket.workspace_name}</span>}
          </div>
        </div>

        {/* Details */}
        <div className="mb-4 rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <h2 className="mb-4 text-lg font-semibold text-gray-900">Details</h2>
          <div className="space-y-4">
            {Object.entries(ticket.field_values).map(([key, value]) => (
              <div key={key}>
                <label className="mb-1 block text-sm font-medium capitalize text-gray-500">
                  {fieldLabel(ticket, key)}
                </label>
                <div className="rounded-lg bg-gray-50 p-3">{renderValue(value)}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Attachments */}
        {ticket.attachments.length > 0 && (
          <div className="mb-4 rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
            <h2 className="mb-4 flex items-center gap-2 text-lg font-semibold text-gray-900">
              <Paperclip className="h-5 w-5" />
              Attachments
            </h2>
            <AttachmentList
              attachments={ticket.attachments}
              urlFor={(a) => publicTicketsApi.attachmentUrl(token, a.id!, password)}
            />
          </div>
        )}

        {/* Conversation */}
        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <h2 className="mb-4 flex items-center gap-2 text-lg font-semibold text-gray-900">
            <MessageSquare className="h-5 w-5" />
            Updates
          </h2>
          {ticket.responses.length === 0 ? (
            <p className="text-sm text-gray-500">No updates yet.</p>
          ) : (
            <div className="space-y-4">
              {ticket.responses.map((r) => (
                <div key={r.id} className="rounded-lg border border-gray-100 p-4">
                  <div className="mb-1 flex items-center gap-2 text-sm">
                    <span className="font-medium text-gray-900">
                      {r.author_name || (r.is_staff ? "Support" : "User")}
                    </span>
                    {r.is_staff && (
                      <span className="flex items-center gap-1 text-xs text-purple-600">
                        <CheckCircle2 className="h-3 w-3" /> Staff
                      </span>
                    )}
                    <span className="text-xs text-gray-400">
                      {formatDate(r.created_at)}
                    </span>
                  </div>
                  <p className="whitespace-pre-wrap text-gray-700">{r.content}</p>
                  {r.attachments && r.attachments.length > 0 && (
                    <div className="mt-3">
                      <AttachmentList
                        attachments={r.attachments}
                        urlFor={(a) => publicTicketsApi.attachmentUrl(token, a.id!, password)}
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Reply box — only for signed-in workspace members */}
          {ticket.can_reply && (
            <div className="mt-6 border-t border-gray-100 pt-4">
              {replyError && (
                <div className="mb-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">
                  {replyError}
                </div>
              )}
              <textarea
                value={reply}
                onChange={(e) => setReply(e.target.value)}
                placeholder="Write a reply…"
                rows={3}
                className="w-full rounded-lg border border-gray-200 p-3 text-gray-900 focus:border-transparent focus:outline-none focus:ring-2 focus:ring-purple-500"
              />
              <div className="mt-2 flex justify-end">
                <button
                  onClick={submitReply}
                  disabled={sendingReply || !reply.trim()}
                  className="flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-white transition hover:bg-purple-500 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {sendingReply ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Send className="h-4 w-4" />
                  )}
                  Reply
                </button>
              </div>
            </div>
          )}
        </div>

        <p className="mt-6 text-center text-xs text-gray-400">Powered by Aexy</p>
      </div>
    </div>
  );
}

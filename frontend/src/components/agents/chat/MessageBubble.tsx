"use client";

import { useState } from "react";
import { Bot, Check, Copy, RotateCw, User } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { AgentMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ToolCallDisplay } from "./ToolCallDisplay";
import { ThinkingIndicator } from "./ThinkingIndicator";

interface MessageBubbleProps {
  message: AgentMessage;
  /** Optional resend handler. When provided, user messages render
   *  a small "Resend" button that re-fires the same prompt as a new
   *  user message. Edit happens in the input field after — once the
   *  text is dropped in, the user can tweak and send. */
  onResend?: (content: string) => void;
}

function formatTime(dateString: string, locale: string): string {
  const date = new Date(dateString);
  return date.toLocaleTimeString(locale, {
    hour: "2-digit",
    minute: "2-digit",
  });
}

// URLs in assistant output (markdown links + citations) come from a
// model that may have been instructed by sender-controlled content, so
// gate the href on http(s). Blocks `javascript:` / `data:` / `vbscript:`
// at the source — rel="noopener noreferrer" doesn't help against
// non-http schemes. mailto: and tel: would be safe too but are not
// expected here; we'd rather render as text than guess intent.
function isSafeUrl(href: string | undefined | null): href is string {
  if (!href) return false;
  const trimmed = href.trim();
  return /^https?:\/\//i.test(trimmed);
}

// Minimal markdown component overrides — render assistant outputs as
// real prose (headings, lists, code, links) rather than as a single
// whitespace-preserved paragraph. We deliberately keep the surface
// small (no images, no raw HTML — react-markdown's default behavior)
// so the chat surface doesn't become an attack surface for tool-call
// outputs that embed sender-controlled content.
const MARKDOWN_COMPONENTS = {
  p: ({ children }: { children?: React.ReactNode }) => (
    <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>
  ),
  ul: ({ children }: { children?: React.ReactNode }) => (
    <ul className="list-disc pl-5 mb-2 last:mb-0 space-y-1">{children}</ul>
  ),
  ol: ({ children }: { children?: React.ReactNode }) => (
    <ol className="list-decimal pl-5 mb-2 last:mb-0 space-y-1">{children}</ol>
  ),
  li: ({ children }: { children?: React.ReactNode }) => (
    <li className="leading-relaxed">{children}</li>
  ),
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => {
    // External by default — react-markdown only sees what the model
    // emitted, never a same-origin internal route, so noopener is the
    // right default. Non-http(s) schemes (javascript:/data:/...) are
    // dropped back to plain text since rel="noopener" doesn't protect
    // against URL-scheme XSS.
    if (!isSafeUrl(href)) {
      return <span>{children}</span>;
    }
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-indigo-400 hover:text-indigo-300 underline"
      >
        {children}
      </a>
    );
  },
  code: ({
    inline,
    className,
    children,
  }: {
    inline?: boolean;
    className?: string;
    children?: React.ReactNode;
  }) => {
    if (inline) {
      return (
        <code className="px-1 py-0.5 rounded bg-background/60 text-[0.9em] font-mono">
          {children}
        </code>
      );
    }
    return (
      <code className={cn("text-sm font-mono", className)}>{children}</code>
    );
  },
  pre: ({ children }: { children?: React.ReactNode }) => (
    <pre className="mb-2 last:mb-0 rounded-lg bg-background/60 border border-border p-3 overflow-x-auto text-xs">
      {children}
    </pre>
  ),
  h1: ({ children }: { children?: React.ReactNode }) => (
    <h1 className="text-base font-semibold mt-3 mb-2 first:mt-0">{children}</h1>
  ),
  h2: ({ children }: { children?: React.ReactNode }) => (
    <h2 className="text-base font-semibold mt-3 mb-2 first:mt-0">{children}</h2>
  ),
  h3: ({ children }: { children?: React.ReactNode }) => (
    <h3 className="text-sm font-semibold mt-3 mb-1.5 first:mt-0">{children}</h3>
  ),
  blockquote: ({ children }: { children?: React.ReactNode }) => (
    <blockquote className="border-l-2 border-border pl-3 my-2 text-muted-foreground italic">
      {children}
    </blockquote>
  ),
};

function MessageContent({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeHighlight]}
      components={MARKDOWN_COMPONENTS}
    >
      {content}
    </ReactMarkdown>
  );
}

function CopyButton({ content }: { content: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API can fail in non-HTTPS contexts or denied
      // permissions — fail silently rather than throwing a toast at
      // every hover-attempted copy.
    }
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      aria-label={copied ? "Copied" : "Copy message"}
      className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent"
    >
      {copied ? (
        <Check className="h-3.5 w-3.5 text-emerald-500" />
      ) : (
        <Copy className="h-3.5 w-3.5" />
      )}
    </button>
  );
}

export function MessageBubble({ message, onResend }: MessageBubbleProps) {
  const locale = useLocale();
  const t = useTranslations("agents.chat");
  const isUser = message.role === "user";
  const isAssistant = message.role === "assistant";
  const isTool = message.role === "tool";
  const isThinking = message.id === "thinking-indicator";

  // Thinking indicator
  if (isThinking) {
    return (
      <div className="flex justify-start">
        <ThinkingIndicator />
      </div>
    );
  }

  // Tool message (displayed inline with assistant messages usually)
  if (isTool) {
    return (
      <div className="flex justify-start pl-11">
        <ToolCallDisplay
          toolName={message.tool_name || "tool"}
          input={message.tool_output?.input as Record<string, unknown>}
          output={message.tool_output?.output}
          status="completed"
        />
      </div>
    );
  }

  // User message
  if (isUser) {
    return (
      <div className="flex justify-end group">
        <div className="flex items-start gap-3 max-w-3xl">
          <div className="flex flex-col items-end">
            <div className="bg-purple-600 text-white rounded-2xl rounded-tr-md px-4 py-3">
              <p className="whitespace-pre-wrap">{message.content}</p>
            </div>
            <div className="flex items-center gap-1 mt-1">
              <CopyButton content={message.content} />
              {/* UX-CHAT-007: Resend on user messages. Re-fires the
                  same prompt as a NEW user message (additive, never
                  destructive — no backend delete needed). Users wanting
                  to edit before resending can copy via the adjacent
                  copy button then paste into the input — and once a
                  proper inline edit affordance lands this becomes a
                  pencil icon. */}
              {onResend ? (
                <button
                  type="button"
                  onClick={() => onResend(message.content)}
                  aria-label="Resend message"
                  title="Resend this prompt"
                  className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent"
                >
                  <RotateCw className="h-3.5 w-3.5" aria-hidden />
                </button>
              ) : null}
              <span className="text-xs text-muted-foreground">
                {formatTime(message.created_at, locale)}
              </span>
            </div>
          </div>
          <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-purple-500/20 flex items-center justify-center">
            <User className="h-4 w-4 text-purple-600 dark:text-purple-300" aria-hidden />
          </div>
        </div>
      </div>
    );
  }

  // Assistant message
  if (isAssistant) {
    const citations = message.citations ?? [];
    const hasUsage =
      message.input_tokens != null ||
      message.output_tokens != null ||
      message.cost_usd != null;
    return (
      <div className="flex justify-start group">
        <div className="flex items-start gap-3 max-w-3xl">
          <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-purple-500/20 flex items-center justify-center">
            <Bot className="h-4 w-4 text-purple-600 dark:text-purple-300" aria-hidden />
          </div>
          <div className="flex flex-col min-w-0">
            <div className="bg-accent/50 rounded-2xl rounded-tl-md px-4 py-3 text-foreground">
              {message.content ? (
                <MessageContent content={message.content} />
              ) : (
                <p className="text-muted-foreground italic">{t("processing")}</p>
              )}

              {/* Display tool calls if present */}
              {message.tool_calls && message.tool_calls.length > 0 && (
                <div className="mt-3 space-y-2">
                  {message.tool_calls.map((call, idx) => (
                    <ToolCallDisplay
                      key={call.id || idx}
                      toolName={call.name}
                      input={call.args}
                      status="completed"
                    />
                  ))}
                </div>
              )}

              {/* UX-CHAT-008: citations strip — sources the agent
                  referenced. Real <a> with rel=noopener so middle-
                  click + cmd-click work and sender-controlled URLs
                  can't hijack the opener. */}
              {citations.length > 0 ? (
                <div className="mt-3 pt-3 border-t border-border/60">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground/80 mb-2">
                    {t("sources")}
                  </div>
                  <ol className="space-y-1.5 list-decimal pl-4">
                    {citations.map((c, i) => {
                      const href = c.url ?? "";
                      const safe = isSafeUrl(href);
                      let host = "";
                      if (safe) {
                        try {
                          host = new URL(href).hostname.replace(/^www\./, "");
                        } catch {
                          host = "";
                        }
                      }
                      return (
                        <li key={`${i}-${href}`} className="text-xs">
                          {safe ? (
                            <a
                              href={href}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-indigo-600 dark:text-indigo-400 hover:underline break-all"
                            >
                              {c.title || host || href}
                            </a>
                          ) : (
                            <span>{c.title || t("untitledSource")}</span>
                          )}
                          {host && c.title ? (
                            <span className="ml-1.5 text-muted-foreground">· {host}</span>
                          ) : null}
                        </li>
                      );
                    })}
                  </ol>
                </div>
              ) : null}
            </div>
            <div className="flex flex-col sm:flex-row sm:items-center gap-1 mt-1">
              {message.content ? (
                <CopyButton content={message.content} />
              ) : null}
              <span className="text-xs text-muted-foreground">
                {formatTime(message.created_at, locale)}
              </span>
              {/* UX-CHAT-009: post-stream token + cost meter. Lives
                  in the message footer (the live meter above the
                  input handles the streaming phase). title= carries
                  the breakdown so power users can audit. Stacks under
                  the timestamp on narrow screens so the meter doesn't
                  push the timestamp off-screen on phones. */}
              {hasUsage ? (
                <span
                  className="sm:ml-1 text-[10px] tabular-nums text-muted-foreground/70"
                  title={[
                    message.input_tokens != null ? `${message.input_tokens} ${t("tokensIn")}` : null,
                    message.output_tokens != null ? `${message.output_tokens} ${t("tokensOut")}` : null,
                    message.cost_usd != null ? `$${message.cost_usd.toFixed(4)}` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                >
                  {message.output_tokens != null ? `${message.output_tokens}t` : ""}
                  {message.cost_usd != null ? ` · $${message.cost_usd.toFixed(4)}` : ""}
                </span>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    );
  }

  // System message
  return (
    <div className="flex justify-center">
      <div className="bg-accent/30 rounded-lg px-4 py-2 text-sm text-muted-foreground max-w-2xl text-center">
        {message.content}
      </div>
    </div>
  );
}

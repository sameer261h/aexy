"use client";

import { useState } from "react";
import { Bot, Check, Copy, User } from "lucide-react";
import { useLocale } from "next-intl";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { AgentMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ToolCallDisplay } from "./ToolCallDisplay";
import { ThinkingIndicator } from "./ThinkingIndicator";

interface MessageBubbleProps {
  message: AgentMessage;
}

function formatTime(dateString: string, locale: string): string {
  const date = new Date(dateString);
  return date.toLocaleTimeString(locale, {
    hour: "2-digit",
    minute: "2-digit",
  });
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
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
    // External by default — react-markdown only sees what the model
    // emitted, never a same-origin internal route, so noopener is the
    // right default.
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-indigo-400 hover:text-indigo-300 underline"
    >
      {children}
    </a>
  ),
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

export function MessageBubble({ message }: MessageBubbleProps) {
  const locale = useLocale();
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
              <span className="text-xs text-muted-foreground">
                {formatTime(message.created_at, locale)}
              </span>
            </div>
          </div>
          <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-purple-500/20 flex items-center justify-center">
            <User className="h-4 w-4 text-purple-400" />
          </div>
        </div>
      </div>
    );
  }

  // Assistant message
  if (isAssistant) {
    return (
      <div className="flex justify-start group">
        <div className="flex items-start gap-3 max-w-3xl">
          <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-purple-500/20 flex items-center justify-center">
            <Bot className="h-4 w-4 text-purple-400" />
          </div>
          <div className="flex flex-col min-w-0">
            <div className="bg-accent/50 rounded-2xl rounded-tl-md px-4 py-3 text-foreground">
              {message.content ? (
                <MessageContent content={message.content} />
              ) : (
                <p className="text-muted-foreground italic">Processing...</p>
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
            </div>
            <div className="flex items-center gap-1 mt-1">
              {message.content ? (
                <CopyButton content={message.content} />
              ) : null}
              <span className="text-xs text-muted-foreground">
                {formatTime(message.created_at, locale)}
              </span>
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

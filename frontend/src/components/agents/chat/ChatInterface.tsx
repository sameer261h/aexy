"use client";

import { useEffect, useRef, useState } from "react";
import { Bot, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { AgentMessage, CRMAgent } from "@/lib/api";
import { MessageBubble } from "./MessageBubble";
import { ChatInput } from "./ChatInput";
import { ThinkingIndicator } from "./ThinkingIndicator";

interface ChatInterfaceProps {
  agent: CRMAgent;
  messages: AgentMessage[];
  onSend: (message: string) => Promise<void>;
  isSending: boolean;
  isLoading?: boolean;
  /** When streaming, surface this so the input morphs into a Stop
   *  button (UX-CHAT-003). */
  onStop?: () => void;
  /** Live token + cost meter while a stream is in flight. */
  streamingTokens?: { input?: number; output?: number } | null;
  streamingCostUsd?: number | null;
}

export function ChatInterface({
  agent,
  messages,
  onSend,
  isSending,
  isLoading = false,
  onStop,
  streamingTokens,
  streamingCostUsd,
}: ChatInterfaceProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const [shouldAutoScroll, setShouldAutoScroll] = useState(true);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (shouldAutoScroll && messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, isSending, shouldAutoScroll]);

  // Detect if user scrolled up
  const handleScroll = () => {
    if (messagesContainerRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = messagesContainerRef.current;
      const isAtBottom = scrollHeight - scrollTop - clientHeight < 100;
      setShouldAutoScroll(isAtBottom);
    }
  };

  const handleSend = async (message: string) => {
    setShouldAutoScroll(true);
    await onSend(message);
  };

  if (isLoading) {
    return (
      <div className="flex-1 flex flex-col bg-background animate-pulse">
        <div className="flex-1 p-6 space-y-4">
          <div className="flex gap-3">
            <div className="h-8 w-8 bg-accent rounded-full" />
            <div className="h-16 w-2/3 bg-accent rounded-xl" />
          </div>
          <div className="flex gap-3 justify-end">
            <div className="h-12 w-1/2 bg-accent rounded-xl" />
            <div className="h-8 w-8 bg-accent rounded-full" />
          </div>
          <div className="flex gap-3">
            <div className="h-8 w-8 bg-accent rounded-full" />
            <div className="h-20 w-3/4 bg-accent rounded-xl" />
          </div>
        </div>
        <div className="border-t border-border p-4">
          <div className="h-10 w-full bg-accent rounded-lg" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-background">
      {/* Messages area */}
      <div
        ref={messagesContainerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto"
      >
        <div className="max-w-4xl mx-auto p-6 space-y-6">
          {/* Welcome message if no messages */}
          {messages.length === 0 && (
            <div className="text-center py-12">
              <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-purple-500/20 flex items-center justify-center">
                <Bot className="h-8 w-8 text-purple-400" />
              </div>
              <h2 className="text-xl font-semibold text-foreground mb-2">
                Chat with {agent.name}
              </h2>
              <p className="text-muted-foreground max-w-md mx-auto">
                {agent.description || "Start a conversation with this agent."}
              </p>
              {agent.tools.length > 0 && (
                <div className="mt-4 flex flex-wrap justify-center gap-2">
                  {agent.tools.slice(0, 6).map((tool) => (
                    <span
                      key={tool}
                      className="px-2 py-1 bg-muted text-muted-foreground rounded text-xs"
                    >
                      {tool.replace(/_/g, " ")}
                    </span>
                  ))}
                  {agent.tools.length > 6 && (
                    <span className="px-2 py-1 bg-muted text-muted-foreground rounded text-xs">
                      +{agent.tools.length - 6} more
                    </span>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Messages — pass onResend down so user messages get a
              re-fire affordance. ChatInterface holds the canonical
              send pipeline; MessageBubble doesn't need to know about
              isSending — onResend itself is the same surface as the
              chat input would call. */}
          {messages.map((message) => (
            <MessageBubble
              key={message.id}
              message={message}
              onResend={message.role === "user" && !isSending ? handleSend : undefined}
            />
          ))}

          {/* Thinking indicator: visible while sending, hidden once a
              text_delta has produced visible content in the in-flight
              assistant message so we don't double up on the spinner +
              the streamed reply. */}
          {isSending &&
            (() => {
              const last = messages[messages.length - 1];
              const streamingHasContent =
                last && last.role === "assistant" && !!last.content;
              return streamingHasContent ? null : (
                <div className="flex justify-start">
                  <ThinkingIndicator />
                </div>
              );
            })()}

          {/* Scroll anchor */}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* UX-CHAT-009: live token + cost meter strip. Only renders
          when a stream is in flight + the backend has started
          emitting usage events. Tabular nums so digits don't jitter. */}
      {isSending && (streamingTokens || streamingCostUsd != null) ? (
        <div
          aria-live="polite"
          className="px-4 pt-2 text-[11px] text-muted-foreground/80 flex items-center gap-3 tabular-nums"
        >
          {streamingTokens?.input != null ? (
            <span>{streamingTokens.input} in</span>
          ) : null}
          {streamingTokens?.output != null ? (
            <span>{streamingTokens.output} out</span>
          ) : null}
          {streamingCostUsd != null ? (
            <span>${streamingCostUsd.toFixed(4)}</span>
          ) : null}
        </div>
      ) : null}

      {/* Input area */}
      <ChatInput
        onSend={handleSend}
        isSending={isSending}
        onStop={onStop}
        disabled={!agent.is_active}
        placeholder={
          agent.is_active
            ? `Message ${agent.name}...`
            : "Agent is inactive"
        }
      />
    </div>
  );
}

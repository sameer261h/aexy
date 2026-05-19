"use client";

import { Bot } from "lucide-react";

export function ThinkingIndicator() {
  return (
    // role="status" + sr-only label announces "Agent is thinking" once
    // to screen readers (without re-announcing every tick of the bounce
    // animation). motion-safe: gates the three-dot bounce so reduced-
    // motion users get a static row instead of vestibular trigger.
    <div
      className="flex items-start gap-3 max-w-3xl"
      role="status"
      aria-label="Agent is thinking"
    >
      <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-purple-500/20 flex items-center justify-center">
        <Bot className="h-4 w-4 text-purple-600 dark:text-purple-400" />
      </div>
      <div className="flex-1 bg-accent/50 rounded-2xl rounded-tl-md px-4 py-3">
        <div className="flex items-center gap-1">
          <span
            aria-hidden
            className="w-2 h-2 bg-purple-500 dark:bg-purple-400 rounded-full motion-safe:animate-bounce"
            style={{ animationDelay: "0ms" }}
          />
          <span
            aria-hidden
            className="w-2 h-2 bg-purple-500 dark:bg-purple-400 rounded-full motion-safe:animate-bounce"
            style={{ animationDelay: "150ms" }}
          />
          <span
            aria-hidden
            className="w-2 h-2 bg-purple-500 dark:bg-purple-400 rounded-full motion-safe:animate-bounce"
            style={{ animationDelay: "300ms" }}
          />
        </div>
      </div>
    </div>
  );
}

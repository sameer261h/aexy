"use client";

import { useState, useRef, useEffect, useMemo, KeyboardEvent } from "react";
import { Send, Loader2, Square } from "lucide-react";
import { cn } from "@/lib/utils";

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
  isSending?: boolean;
  placeholder?: string;
  /** When provided + isSending is true, the Send button becomes a
   *  Stop button that calls this callback. UX-CHAT-003. */
  onStop?: () => void;
}

// UX-CHAT-010: surface the keyboard contract. Users coming from Slack
// expect Cmd/Ctrl+Enter to send; users coming from search bars expect
// plain Enter. We accept both, and show the hint in the platform's
// native modifier so the message is correct on Mac + Windows.
function isMacLike() {
  if (typeof navigator === "undefined") return false;
  return /Mac|iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent || "");
}

export function ChatInput({
  onSend,
  disabled = false,
  isSending = false,
  placeholder = "Type a message...",
  onStop,
}: ChatInputProps) {
  const [message, setMessage] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const sendHint = useMemo(
    () => (isMacLike() ? "⌘↵ to send · Shift↵ for newline" : "Ctrl+Enter to send · Shift+Enter for newline"),
    []
  );

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  }, [message]);

  const handleSubmit = () => {
    const trimmed = message.trim();
    if (trimmed && !disabled && !isSending) {
      onSend(trimmed);
      setMessage("");
      // Reset height
      if (textareaRef.current) {
        textareaRef.current.style.height = "auto";
      }
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Accept three send-shapes: plain Enter (default), Cmd+Enter
    // (Slack/macOS convention), Ctrl+Enter (Windows convention).
    // Shift+Enter is reserved for newline.
    const isPlainEnter = e.key === "Enter" && !e.shiftKey && !e.metaKey && !e.ctrlKey;
    const isModEnter = e.key === "Enter" && (e.metaKey || e.ctrlKey);
    if (isPlainEnter || isModEnter) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="flex flex-col gap-1 p-4 border-t border-border bg-muted/50">
      <div className="flex items-end gap-3">
      <div className="flex-1 relative">
        <textarea
          ref={textareaRef}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled || isSending}
          rows={1}
          aria-label="Message"
          aria-describedby="chat-input-hint"
          className={cn(
            "w-full px-4 py-3 bg-accent border border-border rounded-xl",
            "text-foreground placeholder-muted-foreground resize-none",
            "focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-500/50 focus-visible:border-purple-500",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            "max-h-[200px] overflow-y-auto"
          )}
        />
      </div>
      {isSending && onStop ? (
        // UX-CHAT-003: during streaming, the Send button morphs into
        // a Stop button so users can cancel a long-running response
        // without waiting it out. The backend persists whatever was
        // streamed up to the abort and marks the execution as
        // cancelled, so the partial reply isn't lost.
        <button
          onClick={onStop}
          aria-label="Stop generating"
          title="Stop generating"
          className={cn(
            "flex items-center justify-center p-3 rounded-xl transition",
            "bg-foreground text-background hover:bg-foreground/90",
            "focus-visible:ring-2 focus-visible:ring-purple-500"
          )}
        >
          <Square className="h-4 w-4 fill-current" aria-hidden />
        </button>
      ) : (
        <button
          onClick={handleSubmit}
          disabled={!message.trim() || disabled || isSending}
          aria-label={isSending ? "Sending message" : "Send message"}
          className={cn(
            "flex items-center justify-center p-3 rounded-xl transition",
            "bg-purple-600 text-white hover:bg-purple-700",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
        >
          {isSending ? (
            <Loader2 className="h-5 w-5 motion-safe:animate-spin" aria-hidden />
          ) : (
            <Send className="h-5 w-5" aria-hidden />
          )}
        </button>
      )}
      </div>
      <p
        id="chat-input-hint"
        className="text-[11px] text-muted-foreground/80 px-1 select-none"
        aria-hidden
      >
        {sendHint}
      </p>
    </div>
  );
}

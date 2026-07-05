"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { MessageCircle, X, Minus, ExternalLink } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useNotifications } from "@/hooks/useNotifications";
import { useInbox } from "@/hooks/useChat";
import { useChatWebSocketContext } from "@/contexts/ChatWebSocketContext";
import { CommunicatorPanel } from "./CommunicatorPanel";

export function FloatingChatWidget() {
  const pathname = usePathname();

  // Hidden in the macOS embed (the native app hosts the communicator in its own
  // "Chat" section, so the floating widget must not overlay embedded webviews),
  // and on the full /chat and /communicator pages.
  const [embedded, setEmbedded] = useState(false);
  useEffect(() => {
    try {
      if (
        new URLSearchParams(window.location.search).get("embed") === "true" ||
        window.localStorage.getItem("aexy_embed") === "1"
      ) {
        setEmbedded(true);
      }
    } catch {
      /* SSR / no storage */
    }
  }, []);

  if (
    embedded ||
    pathname?.startsWith("/chat") ||
    pathname?.startsWith("/communicator")
  ) {
    return null;
  }

  return <FloatingChatWidgetInner />;
}

function FloatingChatWidgetInner() {
  const { user } = useAuth();
  const { workspaceId } = useChatWebSocketContext();
  const { unreadCount: notifUnread } = useNotifications(user?.id);
  const { data: inboxTopics } = useInbox(workspaceId);

  const [isOpen, setIsOpen] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);

  // Count total inbox unread
  const inboxUnread = inboxTopics?.reduce((sum, t) => sum + (t.unread_count || 0), 0) || 0;
  const totalBadge = inboxUnread + notifUnread;

  if (!isOpen || isMinimized) {
    return (
      <button
        onClick={() => {
          setIsOpen(true);
          setIsMinimized(false);
        }}
        className="fixed bottom-6 right-6 z-50 h-12 w-12 rounded-full bg-primary text-primary-foreground shadow-lg hover:bg-primary/90 transition-all hover:scale-105 flex items-center justify-center"
        title={isMinimized ? "Expand chat" : "Open chat"}
      >
        <MessageCircle className="h-5 w-5" />
        {totalBadge > 0 && (
          <span className="absolute -top-1 -right-1 min-w-[20px] h-5 px-1 flex items-center justify-center text-[10px] font-bold text-white bg-red-500 rounded-full">
            {totalBadge > 99 ? "99+" : totalBadge}
          </span>
        )}
      </button>
    );
  }

  return (
    <div className="fixed bottom-6 right-6 z-50 w-[520px] h-[600px] bg-background border border-border rounded-xl shadow-2xl shadow-black/20 flex flex-col overflow-hidden">
      <CommunicatorPanel
        headerActions={
          <>
            <Link
              href="/chat"
              className="p-1.5 rounded hover:bg-accent text-muted-foreground transition-colors"
              title="Open full view"
            >
              <ExternalLink className="h-3.5 w-3.5" />
            </Link>
            <button
              onClick={() => setIsMinimized(true)}
              className="p-1.5 rounded hover:bg-accent text-muted-foreground transition-colors"
              title="Minimize"
            >
              <Minus className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={() => setIsOpen(false)}
              className="p-1.5 rounded hover:bg-accent text-muted-foreground transition-colors"
              title="Close"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </>
        }
      />
    </div>
  );
}

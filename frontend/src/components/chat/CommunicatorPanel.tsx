"use client";

import { useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { useNotifications } from "@/hooks/useNotifications";
import { useInbox } from "@/hooks/useChat";
import { useChatWebSocketContext } from "@/contexts/ChatWebSocketContext";
import { WidgetChatView } from "./WidgetChatView";
import { WidgetNotificationsView } from "./WidgetNotificationsView";
import { WidgetActivityView } from "./WidgetActivityView";
import { WidgetAskAIView } from "./WidgetAskAIView";
import { cn } from "@/lib/utils";

export type CommunicatorTab = "threads" | "notifications" | "activity" | "ai";

// The Threads / Notifications / Activity / AI panel body, shared by the floating
// widget (wrapped in its window frame) and the full-page /communicator route
// (embedded chromeless in the macOS app). Fills its container.
export function CommunicatorPanel({
  headerActions,
  initialTab = "threads",
}: {
  headerActions?: React.ReactNode;
  initialTab?: CommunicatorTab;
}) {
  const { user } = useAuth();
  const { workspaceId } = useChatWebSocketContext();
  const { unreadCount: notifUnread } = useNotifications(user?.id);
  const { data: inboxTopics } = useInbox(workspaceId);
  const [activeTab, setActiveTab] = useState<CommunicatorTab>(initialTab);

  const inboxUnread = inboxTopics?.reduce((sum, t) => sum + (t.unread_count || 0), 0) || 0;

  return (
    <div className="flex h-full flex-col overflow-hidden bg-background">
      {/* Tab bar */}
      <div className="flex-shrink-0 border-b border-border">
        <div className="flex items-center justify-between px-3 py-2">
          <div className="flex gap-1">
            {([
              { key: "threads", label: "Threads", badge: inboxUnread },
              { key: "notifications", label: "Notifications", badge: notifUnread },
              { key: "activity", label: "Activity", badge: 0 },
              { key: "ai", label: "AI", badge: 0 },
            ] as const).map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={cn(
                  "px-2.5 py-1.5 text-xs font-medium rounded-md transition-colors relative",
                  activeTab === tab.key
                    ? "bg-accent text-foreground"
                    : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
                )}
              >
                {tab.label}
                {tab.badge > 0 && (
                  <span className="ml-1 inline-flex items-center justify-center min-w-[16px] h-4 px-1 text-[9px] font-bold rounded-full bg-red-500 text-white">
                    {tab.badge > 99 ? "99+" : tab.badge}
                  </span>
                )}
              </button>
            ))}
          </div>
          {headerActions && <div className="flex items-center gap-0.5">{headerActions}</div>}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 min-h-0">
        {activeTab === "threads" && <WidgetChatView />}
        {activeTab === "notifications" && <WidgetNotificationsView />}
        {activeTab === "activity" && <WidgetActivityView />}
        {activeTab === "ai" && <WidgetAskAIView />}
      </div>
    </div>
  );
}

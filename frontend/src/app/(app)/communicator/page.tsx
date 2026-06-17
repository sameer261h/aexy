"use client";

import { CommunicatorPanel } from "@/components/chat/CommunicatorPanel";

// Full-window Threads / Notifications / Activity / AI panel. Primarily embedded
// chromeless in the macOS app's "Chat" section (/communicator?embed=true); the
// native window provides the frame, so no pop-out/minimize/close here.
export default function CommunicatorPage() {
  return (
    <div className="h-screen">
      <CommunicatorPanel />
    </div>
  );
}

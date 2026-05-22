"use client";

import { useEffect, useState, useRef } from "react";
import { useAuth } from "@/hooks/useAuth";
import { useWorkspace } from "@/hooks/useWorkspace";
import { NotionSidebar } from "@/components/docs/sidebar";
import { SearchModal } from "@/components/docs/SearchModal";
import { NotificationInbox } from "@/components/docs/NotificationInbox";
import { useRouter, useParams } from "next/navigation";
import { Building2, Plus, Menu, X } from "lucide-react";

export default function DocsLayoutClient({
  children,
}: {
  children: React.ReactNode;
}) {
  const [mounted, setMounted] = useState(false);
  const { user, isLoading, isAuthenticated, logout } = useAuth();
  const {
    currentWorkspaceId,
    currentWorkspaceLoading,
    workspaces,
    workspacesLoading,
    createWorkspace,
    isCreating,
  } = useWorkspace();
  const router = useRouter();
  const params = useParams();
  const [isCreatingWorkspace, setIsCreatingWorkspace] = useState(false);

  // Modal states
  const [showSearch, setShowSearch] = useState(false);
  const [showInbox, setShowInbox] = useState(false);
  // Mobile drawer state — desktop ignores this; the sidebar is always
  // visible there. Below `md` we hide the sidebar off-screen and a
  // hamburger toggles it.
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  const contentRef = useRef<HTMLDivElement>(null);

  // Handle hydration
  useEffect(() => {
    setMounted(true);
  }, []);

  // Cmd+K in /docs scope must reach the doc-scoped SearchModal, not
  // the app-shell global CommandPalette. Both listen on `document`;
  // without `capture: true` + stopImmediatePropagation the global wins
  // (it's mounted earlier in the layout tree). Capture phase here runs
  // BEFORE the bubble-phase listeners the global hook installs.
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        e.stopImmediatePropagation();
        setShowSearch((prev) => !prev);
      }
    };
    document.addEventListener("keydown", handleKeyDown, { capture: true });
    return () =>
      document.removeEventListener("keydown", handleKeyDown, { capture: true });
  }, []);

  // Close the mobile drawer whenever the route changes — without this
  // the drawer stays open after picking a doc from the sidebar.
  useEffect(() => {
    setMobileSidebarOpen(false);
  }, [params?.documentId]);

  const handleCreateWorkspace = async () => {
    setIsCreatingWorkspace(true);
    try {
      await createWorkspace({
        name: "My Workspace",
      });
    } catch (error) {
      console.error("Failed to create workspace:", error);
    } finally {
      setIsCreatingWorkspace(false);
    }
  };

  // Redirect if not authenticated
  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push("/");
    }
  }, [isLoading, isAuthenticated, router]);

  if (!mounted || isLoading || currentWorkspaceLoading || workspacesLoading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="relative">
            <div className="w-12 h-12 border-4 border-primary-500/20 rounded-full"></div>
            <div className="w-12 h-12 border-4 border-primary-500 border-t-transparent rounded-full animate-spin absolute top-0 left-0"></div>
          </div>
          <p className="text-muted-foreground text-sm">Loading...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  // Show workspace creation prompt if no workspaces exist
  if (workspaces.length === 0) {
    return (
      <div className="min-h-screen bg-background flex flex-col">
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center max-w-md mx-auto px-4">
            <div className="w-16 h-16 bg-gradient-to-br from-primary-500/20 to-purple-500/20 rounded-2xl flex items-center justify-center mx-auto mb-6">
              <Building2 className="h-8 w-8 text-primary-400" />
            </div>
            <h2 className="text-2xl font-bold text-foreground mb-3">
              Create a Workspace
            </h2>
            <p className="text-muted-foreground mb-6">
              You need a workspace to start creating documentation. Workspaces help you organize documents and collaborate with your team.
            </p>
            <button
              onClick={handleCreateWorkspace}
              disabled={isCreatingWorkspace || isCreating}
              className="inline-flex items-center gap-2 px-6 py-3 bg-primary-600 hover:bg-primary-700 text-white font-medium rounded-lg transition disabled:opacity-50"
            >
              {isCreatingWorkspace || isCreating ? (
                <>
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Creating...
                </>
              ) : (
                <>
                  <Plus className="h-5 w-5" />
                  Create Workspace
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen bg-background flex flex-col md:flex-row overflow-hidden">
      {/* Mobile top bar — visible below md, holds the docs-scoped
          hamburger. Sits to the right of pl-14 so the app-shell's
          fixed top-left sidebar trigger (also at top-4 left-4) doesn't
          overlap the docs hamburger. */}
      <div className="md:hidden flex items-center gap-2 pl-14 pr-3 h-12 border-b border-border/50 bg-background/95 backdrop-blur-xl flex-shrink-0">
        <button
          type="button"
          onClick={() => setMobileSidebarOpen(true)}
          aria-label="Open docs sidebar"
          data-testid="docs-mobile-menu-trigger"
          className="p-2 hover:bg-accent rounded-lg transition"
        >
          <Menu className="h-5 w-5 text-foreground" />
        </button>
        <span className="text-foreground font-semibold text-sm">Docs</span>
      </div>

      {/* Mobile backdrop — only renders when drawer is open. */}
      {mobileSidebarOpen && (
        <div
          className="md:hidden fixed inset-0 bg-black/40 z-40"
          onClick={() => setMobileSidebarOpen(false)}
          aria-hidden
        />
      )}

      {/* Main Layout — sidebar + content */}
      <div className="flex flex-1 min-h-0">
        {/* Sidebar:
            - desktop (md+): static 240px column
            - mobile: fixed-position drawer, translated off-screen until open */}
        <div
          data-testid="docs-sidebar"
          className={`w-60 flex-shrink-0 h-full bg-card transition-transform duration-200
            fixed inset-y-0 left-0 z-50 md:relative md:translate-x-0
            ${mobileSidebarOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"}
          `}
        >
          {/* Mobile-only close affordance inside the drawer */}
          <div className="md:hidden flex justify-end px-2 pt-2">
            <button
              type="button"
              onClick={() => setMobileSidebarOpen(false)}
              aria-label="Close sidebar"
              className="p-2 hover:bg-accent rounded-lg transition"
            >
              <X className="h-4 w-4 text-muted-foreground" />
            </button>
          </div>
          {currentWorkspaceId && (
            <NotionSidebar
              selectedDocumentId={params?.documentId as string | undefined}
              onOpenSearch={() => setShowSearch(true)}
              onOpenInbox={() => setShowInbox(true)}
            />
          )}
        </div>

        {/* Main Content */}
        <div
          ref={contentRef}
          className="flex-1 overflow-y-auto"
        >
          {children}
        </div>
      </div>

      {/* Search Modal */}
      <SearchModal
        workspaceId={currentWorkspaceId}
        isOpen={showSearch}
        onClose={() => setShowSearch(false)}
      />

      {/* Notification Inbox */}
      <NotificationInbox
        workspaceId={currentWorkspaceId}
        isOpen={showInbox}
        onClose={() => setShowInbox(false)}
      />
    </div>
  );
}

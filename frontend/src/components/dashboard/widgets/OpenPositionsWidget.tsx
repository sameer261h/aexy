"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Briefcase,
  ChevronRight,
} from "lucide-react";
import { useWorkspace } from "@/hooks/useWorkspace";
import { hiringApi } from "@/lib/api";

export function OpenPositionsWidget() {
  const { currentWorkspace } = useWorkspace();
  const workspaceId = currentWorkspace?.id || null;
  const { data: requirements = [], isLoading } = useQuery({
    queryKey: ["hiring", "requirements", workspaceId],
    queryFn: () => hiringApi.listRequirements(workspaceId as string),
    enabled: !!workspaceId,
  });

  if (isLoading) {
    return (
      <div className="bg-background/50 border border-border rounded-xl p-6 animate-pulse">
        <div className="h-6 w-36 bg-muted rounded mb-4" />
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-12 bg-muted rounded-lg" />
          ))}
        </div>
      </div>
    );
  }

  // "Open" positions are those still being hired for — exclude filled/cancelled.
  const openRequirements = requirements.filter(
    (r) => r.status === "active" || r.status === "draft"
  );

  return (
    <div className="bg-background/50 border border-border rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className="p-1.5 bg-emerald-500/10 rounded-lg shrink-0">
            <Briefcase className="h-4 w-4 text-emerald-400" />
          </div>
          <h3 className="text-sm font-semibold text-foreground truncate">
            Open Positions
          </h3>
        </div>
        <Link
          href="/hiring"
          className="text-emerald-400 hover:text-emerald-300 text-xs flex items-center gap-0.5 transition whitespace-nowrap shrink-0"
        >
          View All <ChevronRight className="w-4 h-4" />
        </Link>
      </div>
      <div className="p-6">
        {!currentWorkspace ? (
          <div className="text-center py-6">
            <div className="w-16 h-16 bg-muted rounded-full flex items-center justify-center mx-auto mb-4">
              <Briefcase className="w-8 h-8 text-muted-foreground" />
            </div>
            <p className="text-muted-foreground text-sm">
              Select a workspace to view open positions.
            </p>
          </div>
        ) : openRequirements.length > 0 ? (
          <div className="space-y-2">
            {openRequirements.slice(0, 5).map((requirement) => (
              <Link
                key={requirement.id}
                href={`/hiring/${requirement.id}`}
                className="flex items-center justify-between p-2 bg-muted/30 rounded-lg hover:bg-muted/50 transition"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <Briefcase className="h-4 w-4 text-emerald-400 shrink-0" />
                  <span className="text-sm text-foreground truncate">
                    {requirement.role_title}
                  </span>
                </div>
                <span className="text-xs text-muted-foreground capitalize whitespace-nowrap ml-2">
                  {requirement.priority}
                </span>
              </Link>
            ))}
            {openRequirements.length > 5 && (
              <div className="text-center text-muted-foreground text-xs pt-1">
                +{openRequirements.length - 5} more positions
              </div>
            )}
          </div>
        ) : (
          <div className="text-center py-6">
            <div className="w-16 h-16 bg-muted rounded-full flex items-center justify-center mx-auto mb-4">
              <Briefcase className="w-8 h-8 text-muted-foreground" />
            </div>
            <p className="text-muted-foreground text-sm">
              No open positions.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

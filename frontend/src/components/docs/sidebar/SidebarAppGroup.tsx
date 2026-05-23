"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronRight, LucideIcon } from "lucide-react";

import { SidebarItemConfig } from "@/config/sidebarLayouts";

interface SidebarAppGroupProps {
  href: string;
  label: string;
  icon: LucideIcon;
  subItems: SidebarItemConfig[];
  defaultExpanded?: boolean;
}

/**
 * Row with a chevron that expands to show child items. Used by the docs
 * sidebar's grouped Apps section to mirror the main sidebar's
 * tracking/sprints/etc. with nested sub-items.
 */
export function SidebarAppGroup({
  href,
  label,
  icon: Icon,
  subItems,
  defaultExpanded = false,
}: SidebarAppGroupProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const hasChildren = subItems.length > 0;

  return (
    <div>
      <div className="group flex items-center gap-1 px-2 py-1.5 mx-1 hover:bg-accent/50 rounded-md transition-colors">
        {hasChildren ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="p-0.5 -ml-0.5 rounded hover:bg-accent"
            aria-expanded={expanded}
            aria-label={expanded ? `Collapse ${label}` : `Expand ${label}`}
          >
            <ChevronRight
              className={`h-3 w-3 text-muted-foreground transition-transform duration-150 ${
                expanded ? "rotate-90" : ""
              }`}
            />
          </button>
        ) : (
          <span className="w-4" />
        )}
        <Link
          href={href}
          className="flex items-center gap-2 flex-1 min-w-0 text-foreground/80 hover:text-foreground text-sm"
        >
          <Icon className="h-4 w-4 text-muted-foreground flex-shrink-0" />
          <span className="truncate">{label}</span>
        </Link>
      </div>
      {hasChildren && expanded && (
        <div className="ml-6 mt-0.5 mb-1 space-y-0.5">
          {subItems.map((child) => {
            const ChildIcon = child.icon;
            return (
              <Link
                key={child.href}
                href={child.href}
                className="flex items-center gap-2 px-2 py-1 rounded-md text-foreground/70 hover:text-foreground hover:bg-accent/50 transition-colors text-xs"
              >
                <ChildIcon className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="truncate">{child.label}</span>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

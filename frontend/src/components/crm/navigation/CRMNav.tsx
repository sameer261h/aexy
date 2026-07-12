"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Inbox,
  Activity,
  Calendar,
  Building2,
  Zap,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useWorkspace } from "@/hooks/useWorkspace";
import { useCRMObjects } from "@/hooks/useCRM";

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

const staticItems: NavItem[] = [
  { href: "/crm", label: "Overview", icon: LayoutDashboard },
  { href: "/crm/inbox", label: "Inbox", icon: Inbox },
  { href: "/crm/activities", label: "Activities", icon: Activity },
  { href: "/crm/calendar", label: "Calendar", icon: Calendar },
];

const trailingItems: NavItem[] = [
  { href: "/crm/automations", label: "Automations", icon: Zap },
  { href: "/crm/settings", label: "Settings", icon: Settings },
];

export function CRMNav() {
  const pathname = usePathname();
  const { currentWorkspaceId } = useWorkspace();
  const { objects } = useCRMObjects(currentWorkspaceId);

  const companyObject = objects?.find((object) => object.object_type === "company");
  const companiesHref = companyObject ? `/crm/${companyObject.slug}` : "/crm/company";

  const items: NavItem[] = [
    ...staticItems,
    { href: companiesHref, label: "Companies", icon: Building2 },
    ...trailingItems,
  ];

  return (
    <nav className="border-b border-border bg-background px-6">
      <div className="flex gap-1 overflow-x-auto">
        {items.map((item) => {
          const isActive =
            pathname === item.href ||
            (item.href !== "/crm" && pathname?.startsWith(`${item.href}/`));
          const Icon = item.icon;

          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-2 px-3 py-3 text-sm font-medium whitespace-nowrap border-b-2 -mb-px transition-colors",
                isActive
                  ? "text-foreground border-purple-500"
                  : "text-muted-foreground border-transparent hover:text-foreground hover:border-border"
              )}
            >
              <Icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

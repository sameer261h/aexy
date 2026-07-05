"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { useWorkspace, useWorkspaceAppSettings } from "@/hooks/useWorkspace";
import { getAppIdFromPath } from "@/config/appDefinitions";

const FALLBACK_ROUTE = "/dashboard";

/**
 * Blocks direct navigation to a module that is disabled for the workspace.
 *
 * The sidebar hides disabled modules, but that alone doesn't stop someone from
 * typing the URL. This guard enforces ONLY the workspace-level app toggles
 * (workspace.settings.app_settings) at the route level — mirroring the
 * backend's workspace-toggle guard. Per-member/role access is handled
 * separately by `components/guards/AppAccessGuard.tsx`, which the app layouts
 * mount with a proper access-denied page and request-access flow.
 *
 * The backend defaults every app to enabled, so only an explicit `false`
 * toggle blocks — while settings load, everything is allowed (no flicker, no
 * false redirects). Routes not in the app catalog are always allowed.
 */
export function WorkspaceAppToggleGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const t = useTranslations("common");
  const { currentWorkspace } = useWorkspace();
  const { appSettings } = useWorkspaceAppSettings(currentWorkspace?.id ?? null);

  const settings: Record<string, boolean> = appSettings;
  const appId = getAppIdFromPath(pathname);
  const blocked =
    pathname !== FALLBACK_ROUTE && !!appId && settings[appId] === false;

  useEffect(() => {
    if (blocked) {
      toast.error(t("appDisabledForWorkspace"));
      router.replace(FALLBACK_ROUTE);
    }
  }, [blocked, router, t]);

  // Don't render the disabled module's content while the redirect is in flight.
  if (blocked) {
    return null;
  }

  return <>{children}</>;
}

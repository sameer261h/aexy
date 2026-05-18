"use client";

import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { developerApi, repositoriesApi, Developer } from "@/lib/api";

// Cookie used solely as a *presence* signal for the Next.js middleware so
// it can avoid rendering the authenticated shell to logged-out users.
// Not httpOnly (must be readable by JS to keep in sync with localStorage)
// and not load-bearing for actual auth — the JWT in localStorage is.
const AUTH_PRESENCE_COOKIE = "aexy_authed";

function setAuthPresenceCookie(): void {
  if (typeof document === "undefined") return;
  document.cookie = `${AUTH_PRESENCE_COOKIE}=1; path=/; SameSite=Lax`;
}

function clearAuthPresenceCookie(): void {
  if (typeof document === "undefined") return;
  document.cookie = `${AUTH_PRESENCE_COOKIE}=; path=/; SameSite=Lax; max-age=0`;
}

export function useAuth() {
  const router = useRouter();
  const queryClient = useQueryClient();

  // Defer localStorage read to after hydration to prevent SSR mismatch.
  // Before mount: mounted=false → isResolved=false → layout shows skeleton.
  // After mount: we read localStorage and proceed with auth check.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const hasToken = mounted && !!localStorage.getItem("token");

  // Keep the middleware-visible presence cookie in sync with localStorage on
  // every render. Handles the case where localStorage and cookie diverge
  // (e.g. localStorage cleared in dev tools).
  useEffect(() => {
    if (!mounted) return;
    if (hasToken) setAuthPresenceCookie();
    else clearAuthPresenceCookie();
  }, [mounted, hasToken]);

  const {
    data: user,
    isLoading,
    isFetched,
    error,
  } = useQuery<Developer>({
    queryKey: ["currentUser"],
    queryFn: developerApi.getMe,
    retry: false,
    enabled: hasToken,
  });

  const logout = () => {
    localStorage.removeItem("token");
    clearAuthPresenceCookie();
    queryClient.clear();
    router.push("/");
  };

  const isAuthenticated = !!user && !error;

  // Auth state is definitively known only after mount AND either:
  //  - No token exists (definitely not authed), OR
  //  - The query has completed at least once (success or failure)
  const isResolved = mounted && (!hasToken || isFetched);

  return {
    user,
    isLoading,
    isAuthenticated,
    isResolved,
    logout,
  };
}

export function useSetToken() {
  const queryClient = useQueryClient();
  const router = useRouter();

  return async (token: string) => {
    localStorage.setItem("token", token);
    setAuthPresenceCookie();
    queryClient.invalidateQueries({ queryKey: ["currentUser"] });

    try {
      // Check if there's a pending invite token that needs to be handled
      const pendingInviteToken = localStorage.getItem("pendingInviteToken");
      if (pendingInviteToken) {
        localStorage.removeItem("pendingInviteToken");
        router.push(`/invite/${pendingInviteToken}`);
        return;
      }

      // Check if onboarding is complete
      const status = await repositoriesApi.getOnboardingStatus();
      if (status.completed) {
        router.push("/dashboard");
      } else {
        router.push("/onboarding");
      }
    } catch (error) {
      // If we can't check onboarding status, assume it's not complete
      console.error("Failed to check onboarding status:", error);
      router.push("/onboarding");
    }
  };
}

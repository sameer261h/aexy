"use client";

import { Suspense, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { useSetToken } from "@/hooks/useAuth";
import { consumeOAuthInflight } from "@/lib/oauth";
import { GitBranch } from "lucide-react";

function AuthCallbackContent() {
  const searchParams = useSearchParams();
  const setToken = useSetToken();

  useEffect(() => {
    const handleAuth = async () => {
      const token = searchParams.get("token");
      const error = searchParams.get("error");

      // Strip the token + any other query from the URL bar / history *before*
      // doing anything else with it — otherwise the JWT lingers in the
      // address bar and Referer header during the next navigation. Matches
      // the same scrub done by /p/[publicSlug] on token receive.
      if (typeof window !== "undefined" && window.location.search) {
        window.history.replaceState({}, "", "/auth/callback");
      }

      if (error) {
        console.error("Auth error:", error);
        window.location.href = `/?error=${encodeURIComponent(error)}`;
        return;
      }

      if (!token) {
        const existingToken = localStorage.getItem("token");
        if (existingToken) {
          await setToken(existingToken);
          return;
        }
        window.location.href = "/?error=no_token";
        return;
      }

      // SECURITY: only accept the URL token if *this* tab kicked off an
      // OAuth login moments ago (sessionStorage marker set by
      // OAuthInflightTagger on the relevant <a href> click). Without this
      // gate, an attacker can craft `/auth/callback?token=ATTACKER_JWT` and
      // silently plant their session in any victim who follows the link.
      // See lib/oauth.ts for the rationale.
      if (!consumeOAuthInflight()) {
        if (localStorage.getItem("token") === token) {
          await setToken(token);
          return;
        }
        window.location.href = "/?error=oauth_state_missing";
        return;
      }

      await setToken(token);
    };

    handleAuth();
  }, [searchParams, setToken]);

  return (
    <div className="min-h-screen bg-background flex flex-col items-center justify-center">
      <GitBranch className="h-16 w-16 text-primary-500 mb-4" />
      <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-primary-500 mb-4"></div>
      <p className="text-foreground text-lg">Completing authentication...</p>
    </div>
  );
}

export default function AuthCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-background flex flex-col items-center justify-center">
          <GitBranch className="h-16 w-16 text-primary-500 mb-4" />
          <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-primary-500 mb-4"></div>
          <p className="text-foreground text-lg">Loading...</p>
        </div>
      }
    >
      <AuthCallbackContent />
    </Suspense>
  );
}

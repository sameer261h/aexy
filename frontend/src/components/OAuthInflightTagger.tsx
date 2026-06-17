"use client";

import { useEffect } from "react";
import { installOAuthClickInterceptor } from "@/lib/oauth";

/**
 * Mounts a document-level mousedown listener that marks an OAuth flow as
 * inflight when the user clicks any link to a backend `/auth/<provider>/login`
 * route. The `/auth/callback` handler requires that marker before writing
 * the returned JWT to localStorage; see lib/oauth.ts for the rationale.
 */
export function OAuthInflightTagger() {
  useEffect(() => {
    return installOAuthClickInterceptor();
  }, []);

  return null;
}

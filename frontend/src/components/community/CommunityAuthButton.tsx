"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

/**
 * Header CTA for the public community pages. Those pages are server/ISR
 * rendered, so auth state can't be read at render time — this small client
 * component reads the token from localStorage (same approach as CommunityReply)
 * and swaps the button accordingly: signed-out visitors get "Sign in" (→ /login,
 * with a next= back to where they are); signed-in visitors get "Open app"
 * (→ /dashboard) instead of being told to sign in when they already are.
 */
export function CommunityAuthButton({
  signedOutLabel = "Sign in",
}: {
  signedOutLabel?: string;
}) {
  const [signedIn, setSignedIn] = useState(false);
  const [next, setNext] = useState("/");

  useEffect(() => {
    if (typeof window === "undefined") return;
    setSignedIn(!!localStorage.getItem("token"));
    setNext(window.location.pathname + window.location.search);
  }, []);

  const className =
    "text-sm rounded-lg bg-blue-600 px-3 py-1.5 text-white hover:bg-blue-700";

  if (signedIn) {
    return (
      <Link href="/dashboard" className={className}>
        Open app
      </Link>
    );
  }

  return (
    <Link
      href={`/login?next=${encodeURIComponent(next)}`}
      className={className}
    >
      {signedOutLabel}
    </Link>
  );
}

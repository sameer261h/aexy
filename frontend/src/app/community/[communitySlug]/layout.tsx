import Link from "next/link";
import type { ReactNode } from "react";
import { CommunityAuthButton } from "@/components/community/CommunityAuthButton";

/**
 * Public community shell — deliberately outside the (app) auth group. No auth,
 * no workspace chrome; just a light forum frame that reads on mobile and by
 * crawlers.
 */
export default async function CommunityLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ communitySlug: string }>;
}) {
  const { communitySlug } = await params;
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      <header className="border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
        <div className="mx-auto max-w-4xl px-4 py-4 flex items-center justify-between">
          <Link
            href={`/community/${communitySlug}`}
            className="font-semibold text-gray-900 dark:text-white hover:opacity-80"
          >
            Community
          </Link>
          <CommunityAuthButton signedOutLabel="Sign in to join" />
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-4 py-8">{children}</main>
      <footer className="mx-auto max-w-4xl px-4 py-8 text-center text-sm text-gray-400">
        Powered by Aexy
      </footer>
    </div>
  );
}

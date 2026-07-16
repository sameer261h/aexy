import type { Metadata } from "next";
import Link from "next/link";
import { MessagesSquare } from "lucide-react";
import { getCommunityDirectory, siteBaseUrl } from "@/lib/community-api";
import { CommunityAuthButton } from "@/components/community/CommunityAuthButton";

export const revalidate = 300;

export async function generateMetadata(): Promise<Metadata> {
  const url = `${siteBaseUrl()}/community`;
  const title = "Communities";
  const description =
    "Browse public community forums — discussions, questions, and answers from teams building with Aexy.";
  return {
    title,
    description,
    alternates: { canonical: url },
    openGraph: { title, description, url, type: "website" },
  };
}

/**
 * Public directory root at /community. Lists every community that opted in
 * (enabled AND listed). Communities not listed remain reachable only by their
 * direct /community/{slug} URL. Deliberately self-contained (no per-community
 * chrome) since it sits above the [communitySlug] layout.
 */
export default async function CommunityDirectoryPage() {
  const directory = await getCommunityDirectory();
  const communities = directory?.communities ?? [];

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      <header className="border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
        <div className="mx-auto max-w-4xl px-4 py-4 flex items-center justify-between">
          <span className="font-semibold text-gray-900 dark:text-white">Communities</span>
          <CommunityAuthButton />
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-4 py-8">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-1">
          Public communities
        </h1>
        <p className="text-gray-600 dark:text-gray-400 mb-6">
          Open forums from teams building on Aexy.
        </p>

        {communities.length === 0 ? (
          <div className="rounded-xl border border-dashed border-gray-300 dark:border-gray-700 p-12 text-center text-gray-500">
            No public communities yet.
          </div>
        ) : (
          <ul className="space-y-3">
            {communities.map((c) => (
              <li key={c.community_slug}>
                <Link
                  href={`/community/${c.community_slug}`}
                  className="block rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 hover:border-blue-400 transition-colors"
                >
                  <div className="flex items-start gap-3">
                    {c.logo_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={c.logo_url}
                        alt=""
                        className="h-8 w-8 rounded shrink-0 object-cover"
                      />
                    ) : (
                      <MessagesSquare className="h-5 w-5 mt-0.5 text-blue-600 shrink-0" />
                    )}
                    <div className="flex-1 min-w-0">
                      <h2 className="font-semibold text-gray-900 dark:text-white truncate">
                        {c.title || c.community_slug}
                      </h2>
                      {c.description && (
                        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400 line-clamp-2">
                          {c.description}
                        </p>
                      )}
                      <p className="mt-2 text-xs text-gray-400">
                        {c.channel_count} {c.channel_count === 1 ? "channel" : "channels"} ·{" "}
                        {c.topic_count} {c.topic_count === 1 ? "topic" : "topics"}
                      </p>
                    </div>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </main>

      <footer className="mx-auto max-w-4xl px-4 py-8 text-center text-sm text-gray-400">
        Powered by Aexy
      </footer>
    </div>
  );
}

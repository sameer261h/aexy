import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { MessagesSquare } from "lucide-react";
import { getCommunity, siteBaseUrl } from "@/lib/community-api";

export const revalidate = 300;

interface Props {
  params: Promise<{ communitySlug: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { communitySlug } = await params;
  const community = await getCommunity(communitySlug);
  if (!community) return { title: "Community not found" };

  const title = community.title || "Community";
  const description =
    community.description || `Join the conversation in the ${title} community.`;
  const url = `${siteBaseUrl()}/community/${communitySlug}`;
  return {
    title,
    description,
    alternates: { canonical: url },
    robots: community.noindex ? { index: false, follow: false } : undefined,
    openGraph: { title, description, url, type: "website" },
  };
}

export default async function CommunityHome({ params }: Props) {
  const { communitySlug } = await params;
  const community = await getCommunity(communitySlug);
  if (!community) notFound();

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          {community.title || "Community"}
        </h1>
        {community.description && (
          <p className="mt-2 text-gray-600 dark:text-gray-400">{community.description}</p>
        )}
      </div>

      {community.channels.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-300 dark:border-gray-700 p-12 text-center text-gray-500">
          No public channels yet.
        </div>
      ) : (
        <ul className="space-y-3">
          {community.channels.map((ch) => (
            <li key={ch.slug}>
              <Link
                href={`/community/${communitySlug}/${ch.slug}`}
                className="block rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 hover:border-blue-400 transition-colors"
              >
                <div className="flex items-start gap-3">
                  <MessagesSquare className="h-5 w-5 mt-0.5 text-blue-600 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <h2 className="font-semibold text-gray-900 dark:text-white truncate">
                      #{ch.name}
                    </h2>
                    {ch.description && (
                      <p className="mt-1 text-sm text-gray-500 dark:text-gray-400 line-clamp-2">
                        {ch.description}
                      </p>
                    )}
                    <p className="mt-2 text-xs text-gray-400">
                      {ch.topic_count} {ch.topic_count === 1 ? "topic" : "topics"} ·{" "}
                      {ch.message_count} {ch.message_count === 1 ? "message" : "messages"}
                    </p>
                  </div>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getCommunity, getCommunityChannel, siteBaseUrl } from "@/lib/community-api";

export const revalidate = 300;

interface Props {
  params: Promise<{ communitySlug: string; channelSlug: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { communitySlug, channelSlug } = await params;
  const [community, channel] = await Promise.all([
    getCommunity(communitySlug),
    getCommunityChannel(communitySlug, channelSlug),
  ]);
  if (!community || !channel) return { title: "Channel not found" };

  const title = `#${channel.name}`;
  const description = channel.description || `Discussions in #${channel.name}.`;
  const url = `${siteBaseUrl()}/community/${communitySlug}/${channelSlug}`;
  return {
    title,
    description,
    alternates: { canonical: url },
    robots: community.noindex ? { index: false, follow: false } : undefined,
    openGraph: { title, description, url, type: "website" },
  };
}

function fmt(date: string | null): string {
  if (!date) return "";
  return new Date(date).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default async function ChannelPage({ params }: Props) {
  const { communitySlug, channelSlug } = await params;
  const channel = await getCommunityChannel(communitySlug, channelSlug);
  if (!channel) notFound();

  return (
    <div>
      <nav className="mb-4 text-sm text-gray-500">
        <Link href={`/community/${communitySlug}`} className="hover:underline">
          Community
        </Link>{" "}
        / <span className="text-gray-900 dark:text-white">#{channel.name}</span>
      </nav>

      <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-1">
        #{channel.name}
      </h1>
      {channel.description && (
        <p className="text-gray-600 dark:text-gray-400 mb-6">{channel.description}</p>
      )}

      {channel.topics.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-300 dark:border-gray-700 p-12 text-center text-gray-500">
          No topics yet.
        </div>
      ) : (
        <ul className="divide-y divide-gray-200 dark:divide-gray-800 rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
          {channel.topics.map((t) => {
            const param = t.slug && t.short_id ? `${t.slug}-${t.short_id}` : null;
            const inner = (
              <div className="flex items-center justify-between p-4">
                <span className="font-medium text-gray-900 dark:text-white truncate">
                  {t.name}
                </span>
                <span className="ml-4 shrink-0 text-xs text-gray-400">
                  {t.message_count} · {fmt(t.last_message_at || t.created_at)}
                </span>
              </div>
            );
            return (
              <li key={`${t.slug}-${t.short_id}`}>
                {param ? (
                  <Link
                    href={`/community/${communitySlug}/${channelSlug}/${param}`}
                    className="block hover:bg-gray-50 dark:hover:bg-gray-800/50"
                  >
                    {inner}
                  </Link>
                ) : (
                  inner
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

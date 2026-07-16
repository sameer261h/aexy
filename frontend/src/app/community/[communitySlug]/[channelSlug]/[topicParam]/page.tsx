import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getCommunity,
  getCommunityTopic,
  siteBaseUrl,
  type PublicMessage,
} from "@/lib/community-api";
import { CommunityReply } from "./CommunityReply";

export const revalidate = 300;

interface Props {
  params: Promise<{ communitySlug: string; channelSlug: string; topicParam: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { communitySlug, channelSlug, topicParam } = await params;
  const [community, topic] = await Promise.all([
    getCommunity(communitySlug),
    getCommunityTopic(communitySlug, channelSlug, topicParam),
  ]);
  if (!community || !topic) return { title: "Topic not found" };

  const title = topic.name;
  const first = topic.messages[0]?.content?.slice(0, 180);
  const description = first || `Discussion in #${topic.channel_name}.`;
  const url = `${siteBaseUrl()}/community/${communitySlug}/${channelSlug}/${topicParam}`;
  // A near-empty topic isn't worth indexing.
  const thin = topic.total < 1;
  return {
    title,
    description,
    alternates: { canonical: url },
    robots: community.noindex || thin ? { index: false, follow: false } : undefined,
    openGraph: { title, description, url, type: "article" },
  };
}

function fmt(date: string): string {
  return new Date(date).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Serialize a JSON-LD object for embedding in a <script> via
 * dangerouslySetInnerHTML. JSON.stringify does NOT escape "<", ">", or the JS
 * line separators, so user-authored content (topic titles, message bodies)
 * could otherwise break out of the script block (e.g. "</script>...") and
 * inject markup. Escape those code points to their \uXXXX forms — still valid
 * JSON, but inert inside HTML.
 */
function safeJsonLd(value: unknown): string {
  return JSON.stringify(value)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

/**
 * Render message text safely: React escapes by default, so we only split on
 * newlines to preserve line breaks. (Rich formatting / attachment rewriting is
 * a later hardening step.)
 */
function MessageBody({ content }: { content: string }) {
  const lines = content.split("\n");
  return (
    <div className="whitespace-pre-wrap break-words text-gray-800 dark:text-gray-200">
      {lines.map((line, i) => (
        <span key={i}>
          {line}
          {i < lines.length - 1 && <br />}
        </span>
      ))}
    </div>
  );
}

function MessageItem({ message }: { message: PublicMessage }) {
  return (
    <li className="p-4">
      <div className="flex items-baseline gap-2 mb-1">
        <span className="font-semibold text-gray-900 dark:text-white">
          {message.author}
        </span>
        <time
          dateTime={message.created_at}
          className="text-xs text-gray-400"
        >
          {fmt(message.created_at)}
        </time>
        {message.is_edited && <span className="text-xs text-gray-400">(edited)</span>}
      </div>
      <MessageBody content={message.content} />
    </li>
  );
}

export default async function TopicPage({ params }: Props) {
  const { communitySlug, channelSlug, topicParam } = await params;
  const topic = await getCommunityTopic(communitySlug, channelSlug, topicParam);
  if (!topic) notFound();

  const base = siteBaseUrl();
  const url = `${base}/community/${communitySlug}/${channelSlug}/${topicParam}`;

  // Structured data: a forum thread + its breadcrumb trail.
  const forumJsonLd = {
    "@context": "https://schema.org",
    "@type": "DiscussionForumPosting",
    headline: topic.name,
    url,
    ...(topic.messages[0] && {
      datePublished: topic.messages[0].created_at,
      author: { "@type": "Person", name: topic.messages[0].author },
      text: topic.messages[0].content,
    }),
    interactionStatistic: {
      "@type": "InteractionCounter",
      interactionType: "https://schema.org/CommentAction",
      userInteractionCount: topic.total,
    },
    comment: topic.messages.slice(1).map((m) => ({
      "@type": "Comment",
      text: m.content,
      datePublished: m.created_at,
      author: { "@type": "Person", name: m.author },
    })),
  };
  const breadcrumbJsonLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Community", item: `${base}/community/${communitySlug}` },
      { "@type": "ListItem", position: 2, name: `#${topic.channel_name}`, item: `${base}/community/${communitySlug}/${channelSlug}` },
      { "@type": "ListItem", position: 3, name: topic.name, item: url },
    ],
  };

  return (
    <div>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: safeJsonLd(forumJsonLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: safeJsonLd(breadcrumbJsonLd) }}
      />

      <nav className="mb-4 text-sm text-gray-500">
        <Link href={`/community/${communitySlug}`} className="hover:underline">
          Community
        </Link>{" "}
        /{" "}
        <Link
          href={`/community/${communitySlug}/${channelSlug}`}
          className="hover:underline"
        >
          #{topic.channel_name}
        </Link>{" "}
        / <span className="text-gray-900 dark:text-white">{topic.name}</span>
      </nav>

      <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-6">
        {topic.name}
      </h1>

      <ul className="divide-y divide-gray-200 dark:divide-gray-800 rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
        {topic.messages.map((m) => (
          <MessageItem key={m.id} message={m} />
        ))}
      </ul>

      {topic.allow_participation ? (
        <CommunityReply
          communitySlug={communitySlug}
          channelSlug={channelSlug}
          topicParam={topicParam}
        />
      ) : (
        <div className="mt-8 rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 text-center">
          <p className="text-gray-600 dark:text-gray-400">
            This is a read-only community.
          </p>
        </div>
      )}
    </div>
  );
}

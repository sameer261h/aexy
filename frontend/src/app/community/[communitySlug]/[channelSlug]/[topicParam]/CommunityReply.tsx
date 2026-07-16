"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { communityPublicApi } from "@/lib/api";

/**
 * Reply box on a public topic. Anonymous visitors see a "sign in" CTA; signed-in
 * visitors (any Aexy user) get a composer that posts to the public reply
 * endpoint. Rendered client-side because auth state lives in localStorage and
 * the surrounding page is statically/ISR rendered.
 */
export function CommunityReply({
  communitySlug,
  channelSlug,
  topicParam,
}: {
  communitySlug: string;
  channelSlug: string;
  topicParam: string;
}) {
  const [signedIn, setSignedIn] = useState(false);
  const [content, setContent] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSignedIn(!!(typeof window !== "undefined" && localStorage.getItem("token")));
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!content.trim()) return;
    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const res = await communityPublicApi.postReply(
        communitySlug,
        channelSlug,
        topicParam,
        content.trim(),
      );
      setContent("");
      if (res.pending_review) {
        setNotice("Thanks! Your reply was submitted and is awaiting moderation.");
      } else {
        setNotice("Reply posted. Refresh to see it in the thread.");
      }
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 429) setError("You're posting too fast — please wait a moment.");
      else if (status === 403) setError("Replies aren't open on this topic.");
      else setError("Could not post your reply. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  if (!signedIn) {
    return (
      <div
        data-testid="community-signin-cta"
        className="mt-8 rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 text-center"
      >
        <p className="text-gray-600 dark:text-gray-400">Want to join the conversation?</p>
        <Link
          href="/"
          className="mt-3 inline-block rounded-lg bg-blue-600 px-4 py-2 text-white hover:bg-blue-700"
        >
          Sign in to reply
        </Link>
      </div>
    );
  }

  return (
    <form
      onSubmit={submit}
      data-testid="community-reply-form"
      className="mt-8 rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5"
    >
      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
        Add a reply
      </label>
      <textarea
        data-testid="community-reply-input"
        value={content}
        onChange={(e) => setContent(e.target.value)}
        rows={3}
        className="w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-transparent px-3 py-2 text-sm"
        placeholder="Share your thoughts…"
      />
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      {notice && (
        <p data-testid="community-reply-notice" className="mt-2 text-sm text-green-600">
          {notice}
        </p>
      )}
      <div className="mt-3 flex justify-end">
        <button
          type="submit"
          disabled={submitting || !content.trim()}
          data-testid="community-reply-submit"
          className="rounded-lg bg-blue-600 px-4 py-2 text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {submitting ? "Posting…" : "Post reply"}
        </button>
      </div>
    </form>
  );
}

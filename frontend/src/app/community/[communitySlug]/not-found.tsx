import Link from "next/link";

/**
 * Rendered when a community/channel/topic under /community/{slug} calls
 * notFound() (unknown slug, disabled community, or a non-public path). Friendlier
 * than the bare app 404 and points visitors to the public directory.
 */
export default function CommunityNotFound() {
  return (
    <div className="mx-auto max-w-lg px-4 py-20 text-center">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
        Nothing here
      </h1>
      <p className="mt-3 text-gray-600 dark:text-gray-400">
        This community page doesn&apos;t exist or isn&apos;t public.
      </p>
      <Link
        href="/community"
        className="mt-6 inline-block rounded-lg bg-blue-600 px-4 py-2 text-white hover:bg-blue-700"
      >
        Browse communities
      </Link>
    </div>
  );
}

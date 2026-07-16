import { getCommunitySitemap, siteBaseUrl } from "@/lib/community-api";

export const revalidate = 3600;

/**
 * Per-community sitemap as a request-time route handler (served at
 * /community/{communitySlug}/sitemap.xml). A route handler — rather than a
 * metadata `sitemap.ts` — because community slugs are unbounded and created at
 * runtime, so there's no static set to enumerate via generateSitemaps().
 *
 * Only ever lists web-public paths: the backend endpoint applies the visibility
 * predicates, and a disabled/noindex community yields an empty urlset.
 */
function xmlEscape(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ communitySlug: string }> },
) {
  const { communitySlug } = await params;
  const data = await getCommunitySitemap(communitySlug);
  const base = siteBaseUrl();
  const root = `${base}/community/${communitySlug}`;

  const urls: string[] = [];
  if (data && !data.noindex) {
    urls.push(`<url><loc>${xmlEscape(root)}</loc></url>`);
    for (const e of data.entries) {
      const loc = xmlEscape(`${root}${e.path}`);
      const lastmod = e.lastmod
        ? `<lastmod>${new Date(e.lastmod).toISOString()}</lastmod>`
        : "";
      urls.push(`<url><loc>${loc}</loc>${lastmod}</url>`);
    }
  }

  const body = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls.join("\n")}
</urlset>`;

  return new Response(body, {
    headers: {
      "Content-Type": "application/xml",
      "Cache-Control": "public, max-age=0, s-maxage=3600",
    },
  });
}

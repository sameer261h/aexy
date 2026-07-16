import Link from "next/link";
import { ArrowRight, CheckCircle2 } from "lucide-react";
import { LandingHeader, LandingFooter } from "@/components/landing/LandingHeader";
import { AuthorByline, defaultAuthor, organizationJsonLd, personJsonLd } from "@/components/marketing/AuthorByline";

export interface GuideSection {
  heading: string;
  paragraphs: string[];
  bullets?: string[];
}

export interface GuideArticleProps {
  slug: string;
  eyebrow: string;
  title: string;
  description: string;
  keyFacts: string[];
  sections: GuideSection[];
  faqs: Array<[string, string]>;
  relatedLinks: Array<[string, string]>;
}

export function GuideArticle({
  slug,
  eyebrow,
  title,
  description,
  keyFacts,
  sections,
  faqs,
  relatedLinks,
}: GuideArticleProps) {
  const url = `https://aexy.io/guides/${slug}`;
  const jsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "Article",
        "@id": `${url}#article`,
        headline: title,
        description,
        url,
        author: { "@id": `https://aexy.io/about#${defaultAuthor.slug}` },
        publisher: { "@id": "https://aexy.io/#organization" },
      },
      {
        "@type": "BreadcrumbList",
        itemListElement: [
          { "@type": "ListItem", position: 1, name: "Home", item: "https://aexy.io" },
          { "@type": "ListItem", position: 2, name: "Guides", item: "https://aexy.io/guides" },
          { "@type": "ListItem", position: 3, name: title, item: url },
        ],
      },
      {
        "@type": "FAQPage",
        mainEntity: faqs.map(([question, answer]) => ({
          "@type": "Question",
          name: question,
          acceptedAnswer: { "@type": "Answer", text: answer },
        })),
      },
      personJsonLd(),
      organizationJsonLd(),
    ],
  };

  return (
    <div className="min-h-screen overflow-hidden bg-[#08090d] text-white">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />
      <div className="fixed inset-0 pointer-events-none bg-[radial-gradient(circle_at_top_left,rgba(45,212,191,0.12),transparent_30%),radial-gradient(circle_at_80%_10%,rgba(168,85,247,0.11),transparent_32%)]" />
      <LandingHeader />

      <main className="relative">
        <article className="px-4 pb-16 pt-32 sm:px-6">
          <div className="mx-auto max-w-3xl">
            <nav className="mb-6 text-sm text-white/40" aria-label="Breadcrumb">
              <Link href="/" className="transition hover:text-white">Home</Link>
              <span className="mx-2 text-white/20">/</span>
              <span className="text-white/60">Guides</span>
              <span className="mx-2 text-white/20">/</span>
              <span className="text-white/60">{eyebrow}</span>
            </nav>

            <h1 className="text-4xl font-semibold leading-[1.08] tracking-tight sm:text-5xl">{title}</h1>
            <p className="mt-6 text-lg leading-8 text-white/62">{description}</p>

            <div className="mt-8">
              <AuthorByline />
            </div>

            <div className="mt-10 rounded-2xl border border-cyan-400/20 bg-cyan-400/[0.06] p-6">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Key facts</p>
              <div className="mt-4 space-y-2.5">
                {keyFacts.map((fact) => (
                  <div key={fact} className="flex gap-3 text-sm leading-6 text-white/75">
                    <CheckCircle2 className="mt-1 h-4 w-4 shrink-0 text-cyan-300" />
                    {fact}
                  </div>
                ))}
              </div>
            </div>

            {sections.map((section) => (
              <section key={section.heading} className="mt-12">
                <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">{section.heading}</h2>
                {section.paragraphs.map((paragraph) => (
                  <p key={paragraph.slice(0, 40)} className="mt-4 text-base leading-7 text-white/62">
                    {paragraph}
                  </p>
                ))}
                {section.bullets && (
                  <ul className="mt-4 space-y-2.5">
                    {section.bullets.map((bullet) => (
                      <li key={bullet} className="flex gap-3 text-base leading-7 text-white/62">
                        <CheckCircle2 className="mt-1.5 h-4 w-4 shrink-0 text-white/40" />
                        {bullet}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            ))}

            <section className="mt-14">
              <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">Frequently asked questions</h2>
              <div className="mt-6 space-y-4">
                {faqs.map(([question, answer]) => (
                  <div key={question} className="rounded-2xl border border-white/10 bg-white/[0.035] p-6">
                    <h3 className="text-lg font-semibold">{question}</h3>
                    <p className="mt-3 text-sm leading-6 text-white/58">{answer}</p>
                  </div>
                ))}
              </div>
            </section>

            <section className="mt-14 rounded-3xl border border-white/10 bg-white/[0.035] p-6 sm:p-8">
              <h2 className="text-xl font-semibold">Keep reading</h2>
              <div className="mt-5 grid gap-3 sm:grid-cols-2">
                {relatedLinks.map(([label, href]) => (
                  <Link key={href} href={href} className="flex items-center justify-between rounded-2xl border border-white/10 bg-black/20 p-4 text-sm font-semibold text-white/75 transition hover:bg-white/[0.06]">
                    {label}
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                ))}
              </div>
            </section>

            <section className="mt-14 text-center">
              <h2 className="text-3xl font-semibold tracking-tight">See it on your own stack.</h2>
              <p className="mx-auto mt-4 max-w-xl text-base leading-7 text-white/56">
                Aexy is open source — self-host it free, or start on cloud in minutes.
              </p>
              <div className="mt-7 flex flex-col justify-center gap-3 sm:flex-row">
                <Link href="/login" className="inline-flex items-center justify-center gap-3 rounded-full bg-white px-7 py-4 font-semibold text-black">
                  Start free
                  <ArrowRight className="h-5 w-5" />
                </Link>
                <Link href="/contact" className="inline-flex items-center justify-center rounded-full border border-white/12 bg-white/[0.04] px-7 py-4 font-semibold text-white">
                  Book demo
                </Link>
              </div>
            </section>
          </div>
        </article>
      </main>

      <LandingFooter />
    </div>
  );
}

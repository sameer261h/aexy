import Link from "next/link";
import { ArrowRight, CheckCircle2, GitBranch } from "lucide-react";
import { LandingFooter, LandingHeader } from "@/components/landing/LandingHeader";
import { AuthorByline, defaultAuthor, organizationJsonLd, personJsonLd } from "@/components/marketing/AuthorByline";

export interface SeoLandingPageProps {
  eyebrow: string;
  title: string;
  description: string;
  primaryCta?: string;
  secondaryCta?: string;
  proofPoints: string[];
  painPoints?: Array<{ problem: string; solution: string }>;
  sections: Array<{
    title: string;
    body: string;
    items: string[];
  }>;
  comparison?: {
    heading: string;
    description: string;
    competitorLabel: string;
    rows: Array<[string, string, string]>;
    links: Array<[string, string]>;
  };
  showPricingCta?: boolean;
  faqs: Array<[string, string]>;
  relatedLinks: Array<[string, string]>;
  schema: Record<string, unknown>;
}

export function SeoLandingPage({
  eyebrow,
  title,
  description,
  primaryCta = "Book demo",
  secondaryCta = "See company OS",
  proofPoints,
  painPoints,
  sections,
  comparison,
  showPricingCta,
  faqs,
  relatedLinks,
  schema,
}: SeoLandingPageProps) {
  const faqSchema = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "FAQPage",
        mainEntity: faqs.map(([question, answer]) => ({
          "@type": "Question",
          name: question,
          acceptedAnswer: { "@type": "Answer", text: answer },
        })),
      },
      {
        "@type": "Article",
        headline: title,
        description,
        author: { "@id": `https://aexy.io/about#${defaultAuthor.slug}` },
        publisher: { "@id": "https://aexy.io/#organization" },
      },
      personJsonLd(),
      organizationJsonLd(),
    ],
  };

  return (
    <div className="min-h-screen overflow-hidden bg-[#08090d] text-white">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(schema) }} />
      {faqs.length > 0 && (
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(faqSchema) }} />
      )}
      <div className="fixed inset-0 pointer-events-none bg-[radial-gradient(circle_at_top_left,rgba(45,212,191,0.14),transparent_30%),radial-gradient(circle_at_80%_10%,rgba(168,85,247,0.13),transparent_32%)]" />
      <LandingHeader />

      <main className="relative">
        <section className="px-4 pb-16 pt-32 sm:px-6">
          <div className="mx-auto max-w-5xl text-center">
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-4 py-2 text-sm text-white/70">
              <GitBranch className="h-4 w-4 text-cyan-300" />
              {eyebrow}
            </div>
            <h1 className="text-5xl font-semibold leading-[1.04] tracking-tight sm:text-6xl">{title}</h1>
            <p className="mx-auto mt-7 max-w-3xl text-lg leading-8 text-white/62">{description}</p>
            <div className="mt-9 flex flex-col justify-center gap-3 sm:flex-row">
              <Link href="/contact" className="inline-flex items-center justify-center gap-3 rounded-full bg-white px-7 py-4 font-semibold text-black">
                {primaryCta}
                <ArrowRight className="h-5 w-5" />
              </Link>
              <Link href="/ai-company-os" className="inline-flex items-center justify-center rounded-full border border-white/12 bg-white/[0.04] px-7 py-4 font-semibold text-white">
                {secondaryCta}
              </Link>
            </div>
          </div>
        </section>

        <section className="px-4 py-10 sm:px-6">
          <div className="mx-auto grid max-w-7xl gap-4 md:grid-cols-3">
            {proofPoints.map((point) => (
              <div key={point} className="rounded-2xl border border-white/10 bg-white/[0.035] p-5 text-sm leading-6 text-white/65">
                <CheckCircle2 className="mb-4 h-5 w-5 text-emerald-300" />
                {point}
              </div>
            ))}
          </div>
        </section>

        {painPoints && painPoints.length > 0 && (
          <section className="px-4 py-16 sm:px-6">
            <div className="mx-auto max-w-5xl">
              <h2 className="text-center text-4xl font-semibold tracking-tight">Sound familiar?</h2>
              <div className="mt-10 space-y-4">
                {painPoints.map(({ problem, solution }) => (
                  <div key={problem} className="grid gap-4 rounded-2xl border border-white/10 bg-white/[0.035] p-6 md:grid-cols-2">
                    <div className="flex items-start gap-3">
                      <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-rose-500/20 text-xs text-rose-300">✕</span>
                      <p className="text-sm leading-6 text-white/55">{problem}</p>
                    </div>
                    <div className="flex items-start gap-3">
                      <CheckCircle2 className="h-6 w-6 shrink-0 text-emerald-300" />
                      <p className="text-sm leading-6 text-white/85">{solution}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}

        <section className="px-4 py-16 sm:px-6">
          <div className="mx-auto grid max-w-7xl gap-4 md:grid-cols-3">
            {sections.map((section) => (
              <div key={section.title} className="rounded-3xl border border-white/10 bg-white/[0.035] p-6">
                <h2 className="text-2xl font-semibold">{section.title}</h2>
                <p className="mt-4 text-sm leading-6 text-white/56">{section.body}</p>
                <div className="mt-6 space-y-3">
                  {section.items.map((item) => (
                    <div key={item} className="flex gap-3 text-sm leading-6 text-white/62">
                      <CheckCircle2 className="mt-1 h-4 w-4 shrink-0 text-cyan-300" />
                      {item}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>

        {comparison && (
          <section className="px-4 py-16 sm:px-6">
            <div className="mx-auto max-w-7xl">
              <div className="max-w-3xl">
                <h2 className="text-4xl font-semibold tracking-tight">{comparison.heading}</h2>
                <p className="mt-5 text-lg leading-8 text-white/56">{comparison.description}</p>
              </div>
              <div className="mt-10 overflow-x-auto rounded-2xl border border-white/10">
                <table className="w-full min-w-[640px] text-left text-sm">
                  <thead>
                    <tr className="border-b border-white/10 bg-white/[0.05]">
                      <th className="px-5 py-4 font-semibold text-white/45"> </th>
                      <th className="px-5 py-4 font-semibold text-cyan-300">Aexy</th>
                      <th className="px-5 py-4 font-semibold text-white/70">{comparison.competitorLabel}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparison.rows.map(([dimension, aexy, them]) => (
                      <tr key={dimension} className="border-b border-white/10 last:border-b-0">
                        <td className="px-5 py-4 font-medium text-white/70">{dimension}</td>
                        <td className="px-5 py-4 leading-6 text-white/85">{aexy}</td>
                        <td className="px-5 py-4 leading-6 text-white/50">{them}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {comparison.links.length > 0 && (
                <div className="mt-6 flex flex-wrap gap-x-6 gap-y-2 text-sm">
                  {comparison.links.map(([label, href]) => (
                    <Link key={href} href={href} className="inline-flex items-center gap-1.5 font-semibold text-white/60 transition hover:text-white">
                      {label}
                      <ArrowRight className="h-4 w-4" />
                    </Link>
                  ))}
                </div>
              )}
            </div>
          </section>
        )}

        {showPricingCta && (
          <section className="px-4 py-16 sm:px-6">
            <div className="mx-auto flex max-w-7xl flex-col items-start gap-6 rounded-3xl border border-white/10 bg-white/[0.035] p-6 sm:p-10 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <h2 className="text-3xl font-semibold tracking-tight">Self-host free. Use cloud when you want speed.</h2>
                <p className="mt-3 max-w-2xl text-lg leading-8 text-white/56">
                  Aexy is open source. Run it on your own infrastructure at no cost, or start on cloud and keep the option to move.
                </p>
              </div>
              <Link href="/pricing" className="inline-flex shrink-0 items-center justify-center gap-3 rounded-full bg-white px-7 py-4 font-semibold text-black">
                See pricing
                <ArrowRight className="h-5 w-5" />
              </Link>
            </div>
          </section>
        )}

        <section className="px-4 py-16 sm:px-6">
          <div className="mx-auto grid max-w-7xl gap-10 rounded-3xl border border-white/10 bg-white/[0.035] p-6 sm:p-10 lg:grid-cols-[0.7fr_1fr]">
            <div>
              <h2 className="text-4xl font-semibold tracking-tight">Related paths</h2>
              <p className="mt-5 text-lg leading-8 text-white/56">
                Route evaluators to the pages that match their buying stage, tool replacement question, or implementation need.
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {relatedLinks.map(([label, href]) => (
                <Link key={href} href={href} className="flex items-center justify-between rounded-2xl border border-white/10 bg-black/20 p-5 text-sm font-semibold text-white/75 transition hover:bg-white/[0.06]">
                  {label}
                  <ArrowRight className="h-4 w-4" />
                </Link>
              ))}
            </div>
          </div>
        </section>

        <section className="px-4 py-16 sm:px-6">
          <div className="mx-auto max-w-4xl">
            <h2 className="text-4xl font-semibold tracking-tight">FAQ</h2>
            <div className="mt-8 space-y-4">
              {faqs.map(([question, answer]) => (
                <div key={question} className="rounded-2xl border border-white/10 bg-white/[0.035] p-6">
                  <h3 className="text-xl font-semibold">{question}</h3>
                  <p className="mt-3 text-sm leading-6 text-white/58">{answer}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="px-4 pb-4 sm:px-6">
          <div className="mx-auto max-w-4xl">
            <p className="mb-3 text-xs font-semibold uppercase tracking-[0.18em] text-white/35">Written by</p>
            <AuthorByline />
          </div>
        </section>
      </main>

      <LandingFooter />
    </div>
  );
}

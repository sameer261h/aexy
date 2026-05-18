const createNextIntlPlugin = require("next-intl/plugin");
const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'github.com',
      },
      {
        protocol: 'https',
        hostname: 'avatars.githubusercontent.com',
      },
      {
        protocol: 'https',
        hostname: 'lh3.googleusercontent.com',
      },
    ],
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  async rewrites() {
    return [
      // Clean booking URLs: /book/* -> /public/book/*
      {
        source: '/book/:path*',
        destination: '/public/book/:path*',
      },
    ];
  },
  async headers() {
    // Clickjacking & frame-busting policy.
    //
    // Embed surfaces (/embed/*) are *intentionally* iframable by customer
    // pages — we control them via `frame-ancestors *` (no DENY) plus a
    // per-link origin allowlist enforced on the API side (WS-074).
    //
    // Everything else (the app shell, admin tools, auth pages, and the
    // marketing landing) is denied framing so an attacker can't render the
    // logged-in shell or the OAuth callback inside a hostile parent and
    // pull off clickjacking or token-bleed attacks.
    const denyFrame = {
      source: "/((?!embed).*)",
      headers: [
        { key: "X-Frame-Options", value: "DENY" },
        { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        { key: "X-Content-Type-Options", value: "nosniff" },
      ],
    };
    const allowEmbedFrame = {
      source: "/embed/:path*",
      headers: [
        // `frame-ancestors *` is intentional — per-link enforcement is on
        // the API side (TableShareLink.allowed_origins, planned). When
        // that's deployed, replace `*` with the per-deployment allowlist.
        { key: "Content-Security-Policy", value: "frame-ancestors *" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        { key: "X-Content-Type-Options", value: "nosniff" },
      ],
    };
    return [denyFrame, allowEmbedFrame];
  },
};

module.exports = withNextIntl(nextConfig);

import type { NextConfig } from "next";

/**
 * The file store's address as the BROWSER reaches it (ADR 0025): uploads go there directly,
 * so the content security policy lists it in connect-src (and media-src, for the call recordings' player). Only an http(s) origin is used; a
 * missing or broken value leaves connect-src out (the policy is report-only for now).
 */
export function fileStoreOrigin(
  raw = process.env.FILE_STORE_ORIGIN,
): string | null {
  if (!raw) return null;
  try {
    const url = new URL(raw);
    return url.protocol === "https:" || url.protocol === "http:"
      ? url.origin
      : null;
  } catch {
    return null;
  }
}

const store = fileStoreOrigin();

const nextConfig: NextConfig = {
  // Cache Components is OFF on purpose: every CRM screen shows per-user data (it reads the
  // session cookie), so pages are rendered on the server for each request. Nothing is cached
  // across users, which removes a whole class of data-leak mistakes.
  cacheComponents: false,
  poweredByHeader: false,
  // Network mode (backend/scripts/network_mode.py): the dev server may be opened through this
  // computer's network address, e.g. from a phone. Empty normally.
  allowedDevOrigins: process.env.NETWORK_HOST ? [process.env.NETWORK_HOST] : [],
  // The development badge ("N") sits bottom-right, so it never covers the sidebar menu.
  devIndicators: { position: "bottom-right" },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          // Report-only first (ADR 0018): browsers log what a stricter policy would block, so
          // nothing breaks while we learn what the screens load. Outside images are the way a
          // poisoned text sends data out, so they are what this policy is about.
          {
            key: "Content-Security-Policy-Report-Only",
            value: [
              "img-src 'self' data:",
              "object-src 'none'",
              "frame-ancestors 'none'",
              "base-uri 'self'",
              ...(store
                ? [`connect-src 'self' ${store}`, `media-src 'self' ${store}`]
                : []),
            ].join("; "),
          },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(self), geolocation=()",
          },
        ],
      },
    ];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;

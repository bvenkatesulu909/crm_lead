import type { NextConfig } from "next";

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
  experimental: {
    // Document uploads go through a Server Action: the API accepts files up to 20 MB, plus
    // room for the form's own bytes. (Default is 1 MB.)
    serverActions: { bodySizeLimit: "21mb" },
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
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


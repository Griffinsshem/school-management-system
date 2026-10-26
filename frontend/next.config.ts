import type { NextConfig } from "next";

// Where the Flask API runs. Read only on the server (never NEXT_PUBLIC_), so
// visitors' browsers never learn it: they only ever talk to this site, and
// src/proxy.ts forwards /api/... to Flask. The login cookie then stays
// first-party. Checked here so a missing or malformed value stops the build
// (and `next start`) instead of failing on the first request.
function apiOrigin(): string {
  const value = process.env.API_ORIGIN;
  if (!value) {
    if (process.env.NODE_ENV === "production") {
      throw new Error("API_ORIGIN must be set. See frontend/.env.example.");
    }
    return "http://127.0.0.1:5000";
  }
  const url = new URL(value);
  if (url.origin !== value || !["http:", "https:"].includes(url.protocol)) {
    throw new Error("API_ORIGIN must be a bare origin such as https://api.example.com");
  }
  return value;
}

apiOrigin();

// Sent with every response. A full Content Security Policy needs per-request
// nonces and is planned separately (see docs/security-notes.md).
const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async headers() {
    return [
      { source: "/:path*", headers: securityHeaders },
      // Invitation links carry a token after "#". Never send this page's
      // address to other sites. (Later entries override earlier ones.)
      {
        source: "/invitations/accept",
        headers: [{ key: "Referrer-Policy", value: "no-referrer" }],
      },
    ];
  },
};

export default nextConfig;

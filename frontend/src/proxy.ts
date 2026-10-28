import { NextResponse, type NextRequest } from "next/server";

// Runs on the server before every matched request (see `config` below).
//
// 1. /api/... is forwarded to the Flask API with two headers that only this
//    server can add: the secret shared with the API (so the API can refuse
//    anyone who calls it directly) and the visitor's IP address (so login
//    limits count each visitor separately). Copies sent by a visitor are
//    always removed first. Both are server-only settings, never NEXT_PUBLIC_.
// 2. Logged-in pages: visitors with no session cookie at all are sent to the
//    login page. This is only a quick, optimistic check; Flask decides on
//    every API request whether a session is valid.

const SESSION_COOKIES = ["__Host-sms_session", "sms_session"];
const PROXY_SECRET_HEADER = "x-sms-proxy-secret";
const CLIENT_IP_HEADER = "x-sms-client-ip";

export function proxy(request: NextRequest) {
  if (request.nextUrl.pathname.startsWith("/api/")) {
    return forwardToApi(request);
  }
  if (SESSION_COOKIES.some((name) => request.cookies.has(name))) {
    return NextResponse.next();
  }
  const login = new URL("/login", request.url);
  login.searchParams.set("next", `${request.nextUrl.pathname}${request.nextUrl.search}`);
  return NextResponse.redirect(login);
}

function forwardToApi(request: NextRequest) {
  // next.config.ts checks API_ORIGIN when the site is built and started.
  const apiOrigin = process.env.API_ORIGIN ?? "http://127.0.0.1:5000";
  const destination = new URL(`${request.nextUrl.pathname}${request.nextUrl.search}`, apiOrigin);

  const headers = new Headers(request.headers);
  headers.delete(PROXY_SECRET_HEADER);
  headers.delete(CLIENT_IP_HEADER);
  const secret = process.env.PROXY_SHARED_SECRET;
  if (secret) {
    headers.set(PROXY_SECRET_HEADER, secret);
    const ip = visitorIp(request);
    if (ip) {
      headers.set(CLIENT_IP_HEADER, ip);
    }
  }
  return NextResponse.rewrite(destination, { request: { headers } });
}

// The visitor's address, from X-Forwarded-For. Only trustworthy where the
// host replaces any value the visitor sent: Vercel does (measured on
// 2026-10-24, see docs/deployment.md); a self-hosted Next.js server does not.
// So it is used only on Vercel, or where TRUST_X_FORWARDED_FOR=1 says the
// host does the same (the local browser tests).
function visitorIp(request: NextRequest): string | undefined {
  if (process.env.VERCEL !== "1" && process.env.TRUST_X_FORWARDED_FOR !== "1") {
    return undefined;
  }
  const first = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  return first || undefined;
}

export const config = {
  // API requests, and the pages that need a login (the login and invitation
  // pages are not listed).
  matcher: [
    "/api/:path*",
    "/",
    "/attendance",
    "/classes",
    "/classes/:id",
    "/classes/:id/attendance",
    "/classes/:id/attendance/summary",
    "/people",
    "/school-year",
    "/students",
    "/students/:id",
  ],
};

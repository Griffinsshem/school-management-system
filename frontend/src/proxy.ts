import { NextResponse, type NextRequest } from "next/server";

// A quick, optimistic check only: visitors with no session cookie at all are
// sent to the login page. Whether a session is valid is decided by Flask on
// every API request; pages handle its 401 by going to the login page too.
const SESSION_COOKIES = ["__Host-sms_session", "sms_session"];

export function proxy(request: NextRequest) {
  if (SESSION_COOKIES.some((name) => request.cookies.has(name))) {
    return NextResponse.next();
  }
  const login = new URL("/login", request.url);
  login.searchParams.set("next", `${request.nextUrl.pathname}${request.nextUrl.search}`);
  return NextResponse.redirect(login);
}

// Pages that need a login. The login and invitation pages are not listed.
export const config = {
  matcher: ["/", "/people", "/students"],
};

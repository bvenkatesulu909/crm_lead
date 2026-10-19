import { NextResponse, type NextRequest } from "next/server";

import { serverConfig } from "@/lib/server/config";
import { refreshSession } from "@/lib/server/oidc";
import {
  SESSION_COOKIE,
  decryptSession,
  encryptSession,
  sessionCookieOptions,
} from "@/lib/server/session";

/**
 * Runs before every page request (see `config.matcher`):
 * 1. No valid session cookie -> redirect to /login (remembering where the user wanted to go).
 * 2. Access token about to expire -> refresh it with Keycloak and store the new tokens.
 *
 * This is a convenience gate only. Real authorization happens in the FastAPI backend on every
 * API call; pages also re-check the session on the server.
 */
const REFRESH_WHEN_SECONDS_LEFT = 30;

export async function proxy(request: NextRequest) {
  const config = serverConfig();
  const session = await decryptSession(
    request.cookies.get(SESSION_COOKIE)?.value,
    config.SESSION_SECRET,
  );
  const now = Math.floor(Date.now() / 1000);

  const toLogin = () => {
    const url = new URL("/login", config.APP_BASE_URL);
    const target = request.nextUrl.pathname + request.nextUrl.search;
    if (target !== "/") url.searchParams.set("returnTo", target);
    const response = NextResponse.redirect(url);
    response.cookies.delete(SESSION_COOKIE);
    return response;
  };

  if (!session || session.refreshTokenExpiresAt <= now) return toLogin();
  if (session.accessTokenExpiresAt - now > REFRESH_WHEN_SECONDS_LEFT)
    return NextResponse.next();

  try {
    const fresh = await refreshSession(session);
    const value = await encryptSession(fresh, config.SESSION_SECRET);
    // Make the new cookie visible to the page rendering in THIS request...
    request.cookies.set(SESSION_COOKIE, value);
    const response = NextResponse.next({
      request: { headers: request.headers },
    });
    // ...and store it in the browser for the next ones.
    response.cookies.set(
      SESSION_COOKIE,
      value,
      sessionCookieOptions(fresh, config.secureCookies),
    );
    return response;
  } catch {
    // Refresh token expired or revoked (e.g. logged out elsewhere, user disabled in Keycloak).
    return toLogin();
  }
}

export const config = {
  // Everything except the login flow itself, the login page and static files.
  matcher: [
    "/((?!api/auth|login|_next/static|_next/image|favicon\\.ico|.*\\.(?:svg|png|ico)$).*)",
  ],
};

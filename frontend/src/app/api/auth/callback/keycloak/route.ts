import { NextResponse, type NextRequest } from "next/server";

import { serverConfig } from "@/lib/server/config";
import { finishLogin } from "@/lib/server/oidc";
import {
  LOGIN_COOKIE,
  SESSION_COOKIE,
  decryptLoginState,
  encryptSession,
  sessionCookieOptions,
} from "@/lib/server/session";

/**
 * GET /api/auth/callback/keycloak?code=...&state=...
 * Keycloak sends the browser here after login. We check `state`, exchange the one-time code
 * (with the PKCE verifier and client secret) for tokens, and store them in the encrypted session.
 */
export async function GET(request: NextRequest) {
  const config = serverConfig();
  const toLogin = (reason: string) => {
    const response = NextResponse.redirect(
      new URL(`/login?error=${reason}`, config.APP_BASE_URL),
    );
    response.cookies.delete(LOGIN_COOKIE);
    return response;
  };

  if (request.nextUrl.searchParams.has("error")) return toLogin("denied");

  const loginState = await decryptLoginState(
    request.cookies.get(LOGIN_COOKIE)?.value,
    config.SESSION_SECRET,
  );
  if (!loginState) return toLogin("expired");

  try {
    // Rebuild the URL from our configured base, not from the Host header a client could set.
    const callbackUrl = new URL(
      request.nextUrl.pathname + request.nextUrl.search,
      config.APP_BASE_URL,
    );
    const session = await finishLogin(callbackUrl, loginState);
    const response = NextResponse.redirect(
      new URL(loginState.returnTo, config.APP_BASE_URL),
    );
    response.cookies.set(
      SESSION_COOKIE,
      await encryptSession(session, config.SESSION_SECRET),
      sessionCookieOptions(session, config.secureCookies),
    );
    response.cookies.delete(LOGIN_COOKIE);
    return response;
  } catch (error) {
    console.error(
      "login callback failed",
      error instanceof Error ? error.message : error,
    );
    return toLogin("failed");
  }
}

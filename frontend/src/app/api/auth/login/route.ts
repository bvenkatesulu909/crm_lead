import { NextResponse, type NextRequest } from "next/server";

import { safeReturnTo } from "@/lib/return-to";
import { serverConfig } from "@/lib/server/config";
import { startLogin } from "@/lib/server/oidc";
import {
  LOGIN_COOKIE,
  encryptLoginState,
  loginCookieOptions,
} from "@/lib/server/session";

/**
 * GET /api/auth/login?returnTo=/leads          (sign in)
 * GET /api/auth/login?register=1&returnTo=/pending   (create an account first)
 * Starts the Authorization Code + PKCE flow: remembers state/nonce/verifier in a short-lived
 * encrypted cookie, then sends the browser to Keycloak's login page.
 */
export async function GET(request: NextRequest) {
  const config = serverConfig();
  const returnTo = safeReturnTo(request.nextUrl.searchParams.get("returnTo"));
  try {
    const register = request.nextUrl.searchParams.get("register") === "1";
    const { url, codeVerifier, state, nonce } = await startLogin({ register });
    const response = NextResponse.redirect(url);
    response.cookies.set(
      LOGIN_COOKIE,
      await encryptLoginState(
        { state, nonce, codeVerifier, returnTo },
        config.SESSION_SECRET,
      ),
      loginCookieOptions(config.secureCookies),
    );
    return response;
  } catch (error) {
    console.error("login: cannot reach identity provider", error);
    return NextResponse.redirect(
      new URL("/login?error=unavailable", config.APP_BASE_URL),
    );
  }
}

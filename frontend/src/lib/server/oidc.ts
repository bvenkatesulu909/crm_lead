import "server-only";

import * as client from "openid-client";

import { serverConfig } from "@/lib/server/config";
import type { Session } from "@/lib/server/session";

/**
 * OpenID Connect with Keycloak, using the certified `openid-client` library:
 * Authorization Code flow + PKCE (S256), `state` (CSRF protection for the login itself)
 * and `nonce` (binds the ID token to this login). The client secret never leaves this server.
 */
let configuration: Promise<client.Configuration> | undefined;

export function oidcConfiguration(): Promise<client.Configuration> {
  if (!configuration) {
    const config = serverConfig();
    const insecureHttp = config.OIDC_ISSUER.startsWith("http://");
    configuration = client
      .discovery(
        new URL(config.OIDC_ISSUER),
        config.OIDC_CLIENT_ID,
        undefined,
        client.ClientSecretPost(config.OIDC_CLIENT_SECRET),
        // Local Keycloak runs on plain HTTP; production must use HTTPS (then this is off).
        insecureHttp ? { execute: [client.allowInsecureRequests] } : undefined,
      )
      .catch((error: unknown) => {
        configuration = undefined; // retry discovery on the next request
        throw error;
      });
  }
  return configuration;
}

export function redirectUri(): string {
  return new URL(
    "/api/auth/callback/keycloak",
    serverConfig().APP_BASE_URL,
  ).toString();
}

/** `register: true` opens Keycloak's sign-up form instead of the sign-in form (OIDC prompt=create). */
export async function startLogin(options: { register?: boolean } = {}) {
  const codeVerifier = client.randomPKCECodeVerifier();
  const state = client.randomState();
  const nonce = client.randomNonce();
  const url = client.buildAuthorizationUrl(await oidcConfiguration(), {
    redirect_uri: redirectUri(),
    scope: "openid profile email",
    code_challenge: await client.calculatePKCECodeChallenge(codeVerifier),
    code_challenge_method: "S256",
    state,
    nonce,
    ...(options.register ? { prompt: "create" } : {}),
  });
  return { url, codeVerifier, state, nonce };
}

function toSession(
  tokens: client.TokenEndpointResponse,
  previousRefreshExpiry?: number,
): Session {
  const now = Math.floor(Date.now() / 1000);
  if (!tokens.access_token || !tokens.refresh_token) {
    throw new Error("Keycloak did not return access and refresh tokens");
  }
  const refreshExpiresIn = Number(tokens.refresh_expires_in ?? 0);
  return {
    accessToken: tokens.access_token,
    refreshToken: tokens.refresh_token,
    accessTokenExpiresAt: now + Number(tokens.expires_in ?? 60),
    refreshTokenExpiresAt:
      refreshExpiresIn > 0
        ? now + refreshExpiresIn
        : (previousRefreshExpiry ?? now + 1800),
  };
}

export async function finishLogin(
  callbackUrl: URL,
  expected: { state: string; nonce: string; codeVerifier: string },
): Promise<Session> {
  const tokens = await client.authorizationCodeGrant(
    await oidcConfiguration(),
    callbackUrl,
    {
      pkceCodeVerifier: expected.codeVerifier,
      expectedState: expected.state,
      expectedNonce: expected.nonce,
      idTokenExpected: true,
    },
  );
  return toSession(tokens);
}

// Keycloak refresh tokens are single-use (rotation). The browser often sends several requests
// at once; they must share ONE refresh instead of racing, or the losers would be logged out.
// Results are kept briefly, keyed by the old refresh token (single server process).
const refreshes = new Map<
  string,
  { result: Promise<Session>; until: number }
>();
const SHARE_REFRESH_MS = 60_000;

export function refreshSession(session: Session): Promise<Session> {
  const now = Date.now();
  for (const [token, entry] of refreshes)
    if (entry.until < now) refreshes.delete(token);
  const existing = refreshes.get(session.refreshToken);
  if (existing) return existing.result;
  const result = oidcConfiguration()
    .then((config) => client.refreshTokenGrant(config, session.refreshToken))
    .then((tokens) => toSession(tokens, session.refreshTokenExpiresAt));
  refreshes.set(session.refreshToken, {
    result,
    until: now + SHARE_REFRESH_MS,
  });
  result.catch(() => refreshes.delete(session.refreshToken));
  return result;
}

/** Ends the Keycloak session server-to-server, so the next login asks for the password again. */
export async function endKeycloakSession(session: Session): Promise<void> {
  const config = serverConfig();
  const endpoint = (await oidcConfiguration()).serverMetadata()
    .end_session_endpoint;
  if (!endpoint) return;
  await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: config.OIDC_CLIENT_ID,
      client_secret: config.OIDC_CLIENT_SECRET,
      refresh_token: session.refreshToken,
    }),
    signal: AbortSignal.timeout(5000),
  }).catch(() => undefined); // logging out locally must still work if Keycloak is down
}

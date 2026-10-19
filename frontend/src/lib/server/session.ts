import "server-only";

import { EncryptJWT, base64url, jwtDecrypt } from "jose";

/**
 * The browser session: Keycloak tokens, ENCRYPTED (AES-256-GCM) into an httpOnly cookie.
 *
 * - The browser stores the cookie but cannot read it (encrypted) or touch it from JavaScript
 *   (httpOnly), so tokens are never exposed to page scripts, localStorage or other sites.
 * - Only this server holds SESSION_SECRET, so a modified cookie fails to decrypt and is ignored.
 * - The ID token is not kept (it would push the cookie over the browser's 4 KB limit, and logout
 *   ends the Keycloak session with the refresh token instead).
 */
export type Session = {
  accessToken: string;
  refreshToken: string;
  /** Seconds since epoch. */
  accessTokenExpiresAt: number;
  refreshTokenExpiresAt: number;
};

/** Short-lived state of a login in progress (between redirect to Keycloak and callback). */
export type LoginState = {
  state: string;
  nonce: string;
  codeVerifier: string;
  returnTo: string;
};

export const SESSION_COOKIE = "crm_session";
export const LOGIN_COOKIE = "crm_login";
const LOGIN_STATE_SECONDS = 10 * 60;

function key(secret: string): Uint8Array {
  return base64url.decode(secret);
}

async function encrypt(
  payload: Record<string, unknown>,
  secret: string,
  expiresAt: number,
) {
  return new EncryptJWT(payload)
    .setProtectedHeader({ alg: "dir", enc: "A256GCM" })
    .setIssuedAt()
    .setExpirationTime(expiresAt)
    .encrypt(key(secret));
}

async function decrypt<T>(
  value: string | undefined,
  secret: string,
): Promise<T | null> {
  if (!value) return null;
  try {
    const { payload } = await jwtDecrypt(value, key(secret), {
      keyManagementAlgorithms: ["dir"],
      contentEncryptionAlgorithms: ["A256GCM"],
    });
    return payload as T;
  } catch {
    // Expired, tampered with, or encrypted with an old secret: treat as "no session".
    return null;
  }
}

export function encryptSession(
  session: Session,
  secret: string,
): Promise<string> {
  return encrypt(session, secret, session.refreshTokenExpiresAt);
}

export async function decryptSession(
  value: string | undefined,
  secret: string,
) {
  const session = await decrypt<Session>(value, secret);
  if (!session || typeof session.accessToken !== "string") return null;
  return session;
}

export function encryptLoginState(
  state: LoginState,
  secret: string,
): Promise<string> {
  return encrypt(
    state,
    secret,
    Math.floor(Date.now() / 1000) + LOGIN_STATE_SECONDS,
  );
}

export function decryptLoginState(value: string | undefined, secret: string) {
  return decrypt<LoginState>(value, secret);
}

export function sessionCookieOptions(session: Session, secure: boolean) {
  return {
    httpOnly: true,
    secure,
    // Lax: sent on normal navigation to our site, NOT on cross-site form posts or fetches.
    sameSite: "lax" as const,
    path: "/",
    maxAge: Math.max(
      0,
      session.refreshTokenExpiresAt - Math.floor(Date.now() / 1000),
    ),
  };
}

export function loginCookieOptions(secure: boolean) {
  return {
    httpOnly: true,
    secure,
    sameSite: "lax" as const,
    path: "/",
    maxAge: LOGIN_STATE_SECONDS,
  };
}

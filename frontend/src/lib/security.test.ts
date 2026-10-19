// @vitest-environment node
import { EncryptJWT, base64url } from "jose";
import { describe, expect, it } from "vitest";

import { safeReturnTo } from "@/lib/return-to";
import {
  type Session,
  decryptLoginState,
  decryptSession,
  encryptLoginState,
  encryptSession,
  sessionCookieOptions,
} from "@/lib/server/session";

const SECRET = base64url.encode(new Uint8Array(32).fill(7));
const OTHER_SECRET = base64url.encode(new Uint8Array(32).fill(9));
const now = () => Math.floor(Date.now() / 1000);

const session: Session = {
  accessToken: "access.token.value",
  refreshToken: "refresh.token.value",
  accessTokenExpiresAt: now() + 300,
  refreshTokenExpiresAt: now() + 1800,
};

describe("encrypted session cookie", () => {
  it("round-trips and does not contain the tokens in readable form", async () => {
    const cookie = await encryptSession(session, SECRET);

    expect(cookie).not.toContain("access.token.value");
    expect(cookie).not.toContain("refresh.token.value");
    expect(await decryptSession(cookie, SECRET)).toMatchObject(session);
  });

  it("rejects a cookie encrypted with another secret", async () => {
    const cookie = await encryptSession(session, OTHER_SECRET);

    expect(await decryptSession(cookie, SECRET)).toBeNull();
  });

  it("rejects a tampered cookie", async () => {
    const cookie = await encryptSession(session, SECRET);
    const parts = cookie.split(".");
    parts[3] = parts[3].slice(0, -2) + (parts[3].endsWith("AA") ? "BB" : "AA");

    expect(await decryptSession(parts.join("."), SECRET)).toBeNull();
  });

  it("rejects an expired cookie", async () => {
    const expired = await encryptSession(
      { ...session, refreshTokenExpiresAt: now() - 10 },
      SECRET,
    );

    expect(await decryptSession(expired, SECRET)).toBeNull();
  });

  it("rejects missing or garbage values", async () => {
    expect(await decryptSession(undefined, SECRET)).toBeNull();
    expect(await decryptSession("not-a-jwe", SECRET)).toBeNull();
  });

  it("rejects an encrypted payload that is not a session", async () => {
    const other = await new EncryptJWT({ hello: "world" })
      .setProtectedHeader({ alg: "dir", enc: "A256GCM" })
      .setExpirationTime("1h")
      .encrypt(base64url.decode(SECRET));

    expect(await decryptSession(other, SECRET)).toBeNull();
  });

  it("uses httpOnly, SameSite=Lax cookies that end with the refresh token", () => {
    const options = sessionCookieOptions(session, true);

    expect(options).toMatchObject({
      httpOnly: true,
      secure: true,
      sameSite: "lax",
      path: "/",
    });
    expect(options.maxAge).toBeGreaterThan(1700);
    expect(options.maxAge).toBeLessThanOrEqual(1800);
  });

  it("keeps login state (PKCE verifier, state, nonce) encrypted too", async () => {
    const state = {
      state: "s",
      nonce: "n",
      codeVerifier: "secret-verifier",
      returnTo: "/leads",
    };
    const cookie = await encryptLoginState(state, SECRET);

    expect(cookie).not.toContain("secret-verifier");
    expect(await decryptLoginState(cookie, SECRET)).toMatchObject(state);
  });
});

describe("safeReturnTo (no open redirects)", () => {
  it.each(["/leads", "/leads?status=new", "/"])(
    "keeps local path %s",
    (path) => {
      expect(safeReturnTo(path)).toBe(path);
    },
  );

  it.each([
    "https://evil.example",
    "//evil.example",
    "/\\evil.example",
    "javascript:alert(1)",
    "leads",
    "/login",
    "/api/auth/login",
    "/ok\u0000//evil",
    "",
    null,
    undefined,
  ])("replaces %s with /", (path) => {
    expect(safeReturnTo(path)).toBe("/");
  });
});

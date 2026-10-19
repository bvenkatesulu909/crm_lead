"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { serverConfig } from "@/lib/server/config";
import { endKeycloakSession } from "@/lib/server/oidc";
import { SESSION_COOKIE, decryptSession } from "@/lib/server/session";

/**
 * Logout as a Server Action: Next.js rejects calls whose Origin is not this site, so another
 * website cannot log users out behind their back (CSRF).
 */
export async function logout(): Promise<never> {
  const config = serverConfig();
  const store = await cookies();
  const session = await decryptSession(
    store.get(SESSION_COOKIE)?.value,
    config.SESSION_SECRET,
  );
  store.delete(SESSION_COOKIE);
  if (session) await endKeycloakSession(session);
  redirect("/login?signed_out=1");
}

"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { FormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";
import { serverConfig } from "@/lib/server/config";
import { refreshSession } from "@/lib/server/oidc";
import {
  SESSION_COOKIE,
  decryptSession,
  encryptSession,
  sessionCookieOptions,
} from "@/lib/server/session";

/**
 * Actions for people who signed up but have no CRM access yet. The code is only a request:
 * the API decides everything (which organisation, whether the e-mail is verified, limits).
 */
export async function requestAccess(
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const code = String(formData.get("signup_code") ?? "")
    .trim()
    .toUpperCase();
  const attempt = previous.attempt + 1;
  if (!/^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$/.test(code)) {
    return {
      attempt,
      values: { signup_code: code },
      fieldErrors: {
        signup_code: "Enter the code in the form XXXX-XXXX-XXXX.",
      },
      error: null,
    };
  }
  try {
    await apiFetch("/onboarding/requests", {
      method: "POST",
      body: JSON.stringify({ signup_code: code }),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return {
      attempt,
      values: { signup_code: code },
      fieldErrors: { signup_code: info.message },
      error: info.status === 422 ? null : info,
    };
  }
  redirect("/pending");
}

/**
 * After approval the new role must be in the access token. Instead of waiting for the next
 * automatic refresh (up to 5 minutes), get fresh tokens now.
 */
export async function continueToCrm(): Promise<never> {
  const config = serverConfig();
  const store = await cookies();
  const session = await decryptSession(
    store.get(SESSION_COOKIE)?.value,
    config.SESSION_SECRET,
  );
  if (!session) redirect("/login");
  try {
    const fresh = await refreshSession(session);
    store.set(
      SESSION_COOKIE,
      await encryptSession(fresh, config.SESSION_SECRET),
      sessionCookieOptions(fresh, config.secureCookies),
    );
  } catch {
    redirect("/login");
  }
  redirect("/");
}

import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";

import { ApiError } from "@/lib/api-error";
import type { Me, ProblemDetails } from "@/lib/api-types";
import { serverConfig } from "@/lib/server/config";
import { SESSION_COOKIE, decryptSession } from "@/lib/server/session";

/**
 * Calls the FastAPI backend FROM THE NEXT.JS SERVER with the user's access token.
 * The browser never sees the token; it only talks to this Next.js server.
 *
 * The backend makes every authorization decision. Hiding a button in the UI is only a
 * convenience - the API rejects the request anyway if the user may not do it.
 */
export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const config = serverConfig();
  const session = await decryptSession(
    (await cookies()).get(SESSION_COOKIE)?.value,
    config.SESSION_SECRET,
  );
  if (!session) redirect("/login");

  let response: Response;
  try {
    response = await fetch(`${config.API_BASE_URL}${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        // File uploads (FormData) set their own multipart Content-Type with a boundary.
        ...(init.body && !(init.body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...init.headers,
        Authorization: `Bearer ${session.accessToken}`,
      },
      cache: "no-store", // per-user data: never cache across users
      signal:
        init.signal ??
        AbortSignal.timeout(init.body instanceof FormData ? 60_000 : 10_000),
    });
  } catch (error) {
    console.error(
      "API unreachable",
      path,
      error instanceof Error ? error.message : error,
    );
    throw new ApiError(503, {
      title: "Service Unavailable",
      status: 503,
      detail: "API unreachable",
    });
  }

  if (response.status === 401) redirect("/login"); // token no longer accepted
  if (!response.ok) {
    const problem = (await response
      .json()
      .catch(() => null)) as ProblemDetails | null;
    throw new ApiError(
      response.status,
      problem ?? {
        title: response.statusText,
        status: response.status,
        detail: response.statusText,
      },
    );
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

/** A file from the API (e.g. a quote PDF), or the error status. */
export type ApiFile =
  | { ok: true; data: ArrayBuffer; contentType: string; fileName: string }
  | { ok: false; status: number };

/**
 * Downloads a file from the API with the user's token, for a route handler to pass on to
 * the browser. Errors come back as a status (no exception), so the handler decides the page.
 */
export async function apiFile(path: string): Promise<ApiFile> {
  const config = serverConfig();
  const session = await decryptSession(
    (await cookies()).get(SESSION_COOKIE)?.value,
    config.SESSION_SECRET,
  );
  if (!session) return { ok: false, status: 401 };
  let response: Response;
  try {
    response = await fetch(`${config.API_BASE_URL}${path}`, {
      headers: { Authorization: `Bearer ${session.accessToken}` },
      cache: "no-store",
      signal: AbortSignal.timeout(30_000),
    });
  } catch {
    return { ok: false, status: 503 };
  }
  if (!response.ok) return { ok: false, status: response.status };
  // The name comes from the API's Content-Disposition; only safe characters are kept.
  const disposition = response.headers.get("content-disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "download";
  return {
    ok: true,
    data: await response.arrayBuffer(),
    contentType:
      response.headers.get("content-type") ?? "application/octet-stream",
    fileName: name.replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 100),
  };
}

/** The signed-in user, loaded once per request (React `cache`). */
export const getMe = cache(() => apiFetch<Me>("/me"));

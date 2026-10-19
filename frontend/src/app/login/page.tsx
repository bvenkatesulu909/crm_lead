import type { Metadata } from "next";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { buttonClass } from "@/components/ui";
import { safeReturnTo } from "@/lib/return-to";
import { serverConfig } from "@/lib/server/config";
import { SESSION_COOKIE, decryptSession } from "@/lib/server/session";

export const metadata: Metadata = { title: "Sign in" };

const MESSAGES: Record<string, string> = {
  expired: "Your sign-in took too long. Please try again.",
  denied: "Sign-in was cancelled or refused.",
  failed: "We couldn't complete your sign-in. Please try again.",
  unavailable:
    "The sign-in service is not reachable right now. Please try again shortly.",
};

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const params = await searchParams;
  const one = (v: string | string[] | undefined) =>
    Array.isArray(v) ? v[0] : v;
  const returnTo = safeReturnTo(one(params.returnTo));

  const config = serverConfig();
  const session = await decryptSession(
    (await cookies()).get(SESSION_COOKIE)?.value,
    config.SESSION_SECRET,
  );
  if (session) redirect(returnTo);

  const error = MESSAGES[one(params.error) ?? ""];
  const signedOut = one(params.signed_out) === "1";

  return (
    <main className="grid min-h-screen place-items-center bg-gradient-to-br from-brand-800 to-brand-600 p-4">
      <div className="w-full max-w-sm rounded-xl bg-white p-8 shadow-xl">
        <div className="mb-6 text-center">
          <span
            aria-hidden="true"
            className="mx-auto grid size-12 place-items-center rounded-lg bg-brand-600 text-lg font-semibold text-white"
          >
            CL
          </span>
          <h1 className="mt-4 text-xl font-semibold text-slate-900">
            Sign in to crm-lead
          </h1>
          <p className="mt-1 text-sm text-slate-600">
            Use your company account.
          </p>
        </div>

        {error && (
          <p
            role="alert"
            className="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-800"
          >
            {error}
          </p>
        )}
        {signedOut && !error && (
          <p
            role="status"
            className="mb-4 rounded-md bg-emerald-50 p-3 text-sm text-emerald-800"
          >
            You have been signed out.
          </p>
        )}

        {/* A plain link (not client navigation): the server starts the OIDC flow and redirects. */}
        <a
          href={`/api/auth/login?returnTo=${encodeURIComponent(returnTo)}`}
          className={`${buttonClass("primary")} w-full py-2.5`}
        >
          Sign in
        </a>
        <p className="mt-4 text-center text-sm text-slate-600">
          New here?{" "}
          <a
            href="/api/auth/login?register=1&returnTo=%2Fpending"
            className="font-medium text-brand-700 hover:underline"
          >
            Create an account
          </a>
          <span className="mt-1 block text-xs text-slate-500">
            You&apos;ll need your organisation&apos;s sign-up code. An
            administrator approves new accounts.
          </span>
        </p>
        <p className="mt-6 text-center text-xs text-slate-500">
          You will be taken to the secure company sign-in page. Your password is
          never seen by this application.
        </p>
      </div>
    </main>
  );
}

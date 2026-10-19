import type { Metadata } from "next";
import type { ReactNode } from "react";

import { logout } from "@/app/actions/auth";
import { ErrorAlert, buttonClass } from "@/components/ui";
import { toErrorInfo } from "@/lib/api-error";
import type { OnboardingStatus } from "@/lib/api-types";
import { initialFormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";

import { continueToCrm, requestAccess } from "./actions";
import { SignupCodeForm } from "./signup-code-form";

export const metadata: Metadata = { title: "Waiting for access" };

/**
 * For people who are signed in (Keycloak) but have no CRM access yet. They see NO CRM data:
 * only their own request status. Members who land here are sent on.
 */
export default async function PendingPage() {
  let status: OnboardingStatus;
  try {
    status = await apiFetch<OnboardingStatus>("/onboarding/status");
  } catch (error) {
    return (
      <Shell>
        <ErrorAlert
          title="We couldn't check your account"
          error={toErrorInfo(error)}
        />
      </Shell>
    );
  }

  if (status.state === "member") {
    return (
      <Shell title="You have access">
        <p className="text-sm text-slate-600">
          Your request was approved. Continue to load your new permissions.
        </p>
        <form action={continueToCrm} className="mt-5">
          <button type="submit" className={`${buttonClass("primary")} w-full`}>
            Continue to crm-lead
          </button>
        </form>
      </Shell>
    );
  }
  if (status.state === "disabled") {
    return (
      <Shell title="Account deactivated">
        <p
          role="alert"
          className="rounded-md bg-red-50 p-3 text-sm text-red-800"
        >
          Your account has been deactivated by your organisation&apos;s
          administrator. Please contact them if you need access again.
        </p>
        <form action={logout} className="mt-6 text-center">
          <button
            type="submit"
            className="text-sm font-medium text-brand-700 hover:underline"
          >
            Sign out
          </button>
        </form>
      </Shell>
    );
  }

  return (
    <Shell title={status.state === "pending" ? "Waiting for approval" : "Request access"}>
      {!status.email_verified ? (
        <p role="alert" className="rounded-md bg-amber-50 p-3 text-sm text-amber-900">
          Please verify your e-mail address first: open the link we sent to {status.email ?? "your e-mail"}, then reload this page.
        </p>
      ) : status.state === "pending" ? (
        <div className="space-y-3 text-sm text-slate-700">
          <p role="status" className="rounded-md bg-sky-50 p-3 text-sky-900">
            Your request to join <strong>{status.organisation_name}</strong> was sent. An administrator of
            your organisation will review it.
          </p>
          <p>You don&apos;t have access to any CRM data until it is approved. Check back later:</p>
          <a href="/pending" className={`${buttonClass("secondary")} w-full`}>Check again</a>
        </div>
      ) : (
        <div className="space-y-4">
          {status.state === "rejected" && (
            <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-800">
              Your last request was not approved. If you think this is a mistake, contact your organisation,
              or enter another code.
            </p>
          )}
          <p className="text-sm text-slate-600">
            You are signed in as <strong>{status.email}</strong>, but your account isn&apos;t linked to an
            organisation yet.
          </p>
          <SignupCodeForm action={requestAccess} initialState={initialFormState} />
        </div>
      )}
      <form action={logout} className="mt-6 border-t border-slate-200 pt-4 text-center">
        <button type="submit" className="text-sm font-medium text-brand-700 hover:underline">Sign out</button>
      </form>
    </Shell>
  ); // prettier-ignore
}

function Shell({
  title = "Your account",
  children,
}: {
  title?: string;
  children: ReactNode;
}) {
  return (
    <main className="grid min-h-screen place-items-center bg-gradient-to-br from-brand-800 to-brand-600 p-4">
      <div className="w-full max-w-md rounded-xl bg-white p-8 shadow-xl">
        <h1 className="mb-4 text-xl font-semibold text-slate-900">{title}</h1>
        {children}
      </div>
    </main>
  ); // prettier-ignore
}

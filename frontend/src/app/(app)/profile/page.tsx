import type { Metadata } from "next";

import { logout } from "@/app/actions/auth";
import { Card, PageHeader, buttonClass } from "@/components/ui";
import { PERMISSION_LABELS, ROLE_LABELS } from "@/lib/permissions";
import { getMe } from "@/lib/server/api";
import { serverConfig } from "@/lib/server/config";

export const metadata: Metadata = { title: "Your profile" };

/** The signed-in employee: who they are, their organisation, roles and what those allow. */
export default async function ProfilePage() {
  const me = await getMe();
  // Passwords and two-factor settings live in Keycloak, never in the CRM.
  const accountConsole = `${serverConfig().OIDC_ISSUER}/account/`;
  const abilities = me.permissions.map((p) => PERMISSION_LABELS[p] ?? p).sort();

  const facts: [string, string][] = [
    ["Name", me.display_name ?? "—"],
    ["E-mail", me.email ?? "—"],
    ["Organisation", me.tenant_name ?? "—"],
    [
      "Roles",
      me.roles.map((r) => ROLE_LABELS[r] ?? r).join(", ") || "No CRM role",
    ],
  ];

  return (
    <>
      <PageHeader
        title="Your profile"
        description="How the CRM knows you, and what your role allows."
      />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <h2 className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">
            Account
          </h2>
          <dl className="grid gap-x-6 gap-y-4 px-5 py-4 sm:grid-cols-2">
            {facts.map(([label, value]) => (
              <div key={label}>
                <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  {label}
                </dt>
                <dd className="mt-1 break-words text-sm text-slate-900">
                  {value}
                </dd>
              </div>
            ))}
          </dl>
          <div className="border-t border-slate-200 px-5 py-4">
            <h3 className="text-sm font-semibold text-slate-900">
              What you can do
            </h3>
            {abilities.length === 0 ? (
              <p className="mt-2 text-sm text-slate-600">
                Your role has no CRM permissions yet.
              </p>
            ) : (
              <ul className="mt-2 grid gap-1 text-sm text-slate-700 sm:grid-cols-2">
                {abilities.map((text) => (
                  <li key={text} className="flex gap-2">
                    <span aria-hidden="true" className="text-emerald-600">
                      ✓
                    </span>
                    {text}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>

        <div className="space-y-6">
          <Card className="p-5">
            <h2 className="text-base font-semibold text-slate-900">
              Password and sign-in
            </h2>
            <p className="mt-1 text-sm text-slate-600">
              Your password and two-step sign-in are managed by the company
              sign-in service, not by the CRM.
            </p>
            <a
              href={accountConsole}
              target="_blank"
              rel="noopener noreferrer"
              className={`${buttonClass("secondary")} mt-4`}
            >
              Manage sign-in settings
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
          </Card>
          <Card className="p-5">
            <h2 className="text-base font-semibold text-slate-900">Sign out</h2>
            <p className="mt-1 text-sm text-slate-600">
              Ends your session here and at the sign-in service.
            </p>
            <form action={logout} className="mt-4">
              <button type="submit" className={buttonClass("secondary")}>
                Sign out
              </button>
            </form>
          </Card>
        </div>
      </div>
    </>
  );
}

import Link from "next/link";
import { redirect } from "next/navigation";

import { ButtonLink, Card, EmptyState, ErrorAlert } from "@/components/ui";
import { UserMenu } from "@/components/user-menu";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import type { Me } from "@/lib/api-types";
import { getMe } from "@/lib/server/api";

/**
 * The customer portal: a separate, simpler area for CUSTOMER users.
 * Staff are told this area isn't for them (and the API refuses their portal calls anyway).
 */
export default async function PortalLayout({
  children,
}: LayoutProps<"/portal">) {
  let me: Me;
  try {
    me = await getMe();
  } catch (error) {
    // Signed up but not approved yet: no CRM data, only the waiting page.
    if (
      error instanceof ApiError &&
      (error.problem.code === "access_pending" ||
        error.problem.code === "account_disabled")
    )
      redirect("/pending");
    return (
      <main className="mx-auto max-w-xl p-6">
        <ErrorAlert
          title="We couldn't load your account"
          error={toErrorInfo(error)}
        />
      </main>
    );
  }

  const name = me.display_name ?? me.email ?? "Signed-in user";

  return (
    <div className="min-h-screen">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-white focus:px-4 focus:py-2 focus:shadow"
      >
        Skip to main content
      </a>
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex h-16 max-w-5xl items-center justify-between gap-4 px-4 sm:px-6">
          <Link
            href="/portal"
            className="flex items-center gap-2 font-semibold text-slate-900"
          >
            <span
              aria-hidden="true"
              className="grid size-8 place-items-center rounded-md bg-brand-600 text-sm text-white"
            >
              CL
            </span>
            <span>
              Customer portal
              {me.tenant_name && (
                <span className="block text-xs font-normal text-slate-500">
                  {me.tenant_name}
                </span>
              )}
            </span>
          </Link>
          <UserMenu
            name={name}
            email={me.email}
            roles={me.roles}
            profileHref={null}
          />
        </div>
      </header>
      <main
        id="main"
        tabIndex={-1}
        className="mx-auto max-w-5xl px-4 py-8 sm:px-6"
      >
        {me.user_type === "customer" ? (
          children
        ) : (
          <Card className="p-6">
            <EmptyState
              title="This area is for customers"
              description="You are signed in as an employee. Please use the CRM instead."
              action={<ButtonLink href="/">Go to the CRM</ButtonLink>}
            />
          </Card>
        )}
      </main>
    </div>
  );
}

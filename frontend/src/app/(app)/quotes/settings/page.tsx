import type { Metadata } from "next";
import Link from "next/link";

import { Card, Forbidden, PageHeader, SuccessAlert } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type { QuoteSettings } from "@/lib/api-types";
import { formatDateTime } from "@/lib/format";
import { canManageQuoteSettings } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { updateQuoteSettings } from "../actions";
import { QuoteSettingsForm } from "./settings-form";

export const metadata: Metadata = { title: "Quote settings" };

/** The organisation's approval limit for quote discounts. Everyone with quotes can read it;
 * only tenant admins can change it (the API enforces that). */
export default async function QuoteSettingsPage({
  searchParams,
}: PageProps<"/quotes/settings">) {
  const query = await searchParams;
  const me = await getMe();
  let settings: QuoteSettings;
  try {
    settings = await apiFetch<QuoteSettings>("/quotes/settings");
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    throw error;
  }
  const limit = String(Number(settings.approval_limit_percent));
  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/quotes" className="font-medium text-brand-700 hover:underline">← Quotes</Link>
      </nav>
      {query.done === "saved" && <div className="mb-4"><SuccessAlert>The approval limit was saved. It applies to quotes submitted from now on.</SuccessAlert></div>}
      <PageHeader title="Quote settings" description="Rules for your whole organisation." />
      <Card className="space-y-4 p-6">
        <div>
          <h2 className="text-base font-semibold text-slate-900">Discount approval</h2>
          <p className="mt-1 text-sm text-slate-600">
            A quote with any line discount <strong>above {limit} %</strong> needs a manager&apos;s approval before it can be sent.
            {settings.version === 0 ? " (This is the standard setting.)" : settings.updated_at && ` Last changed ${formatDateTime(settings.updated_at)}.`}
          </p>
          <p className="mt-1 text-sm text-slate-600">Quotes already waiting for approval keep waiting when the limit changes.</p>
        </div>
        {canManageQuoteSettings(me) ? (
          <QuoteSettingsForm action={updateQuoteSettings.bind(null, settings.version)} current={limit} />
        ) : (
          <p className="text-sm text-slate-500">Only administrators can change this.</p>
        )}
      </Card>
    </>
  ); // prettier-ignore
}

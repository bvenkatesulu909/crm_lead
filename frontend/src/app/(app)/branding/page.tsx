import type { Metadata } from "next";

import { BrandingForm, LogoPanel } from "@/components/branding-views";
import { Card, Forbidden, PageHeader, SuccessAlert } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import { cleanedNotice, type Branding } from "@/lib/branding";
import { formatDateTime } from "@/lib/format";
import { apiFetch, apiFile, getMe } from "@/lib/server/api";

import { removeLogo, saveBranding, uploadLogo } from "./actions";

export const metadata: Metadata = { title: "Branding" };

const DONE: Record<string, string> = {
  saved: "The branding was saved.",
  logo: "The logo was saved.",
  "logo-removed": "The logo was removed.",
};

/**
 * The organisation's branding for proposal decks (ADR 0032): colour, logo and the texts that appear
 * on every deck. Only tenant administrators can open it; the API enforces that.
 */
export default async function BrandingPage({
  searchParams,
}: PageProps<"/branding">) {
  const query = await searchParams;
  const me = await getMe();
  let branding: Branding;
  try {
    branding = await apiFetch<Branding>("/branding");
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    throw error;
  }
  // The stored logo is a small PNG; it is shown inline so the browser never needs a token.
  const file = branding.has_logo ? await apiFile("/branding/logo") : null;
  const logoSrc =
    file && file.ok
      ? `data:image/png;base64,${Buffer.from(file.data).toString("base64")}`
      : null;
  const done = typeof query.done === "string" ? DONE[query.done] : undefined;
  const cleaned =
    typeof query.cleaned === "string" ? query.cleaned.split(",") : [];
  const notice = cleanedNotice(cleaned);
  return (
    <>
      {done && <div className="mb-4"><SuccessAlert>{done}</SuccessAlert></div>}
      <PageHeader
        title="Branding"
        description="The colour, logo and texts that appear on your proposal decks."
      />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="space-y-4 p-6 lg:col-span-2">
          <h2 className="text-base font-semibold text-slate-900">Colour and texts</h2>
          {notice && <p role="note" className="text-sm text-amber-800">{notice}</p>}
          <BrandingForm
            action={saveBranding.bind(null, branding.version)}
            branding={branding}
            organisation={me.tenant_name ?? "Your organisation"}
            logoSrc={logoSrc}
          />
          {branding.updated_at && (
            <p className="text-xs text-slate-500">Last changed {formatDateTime(branding.updated_at)}.</p>
          )}
        </Card>
        <Card className="space-y-4 p-6">
          <h2 className="text-base font-semibold text-slate-900">Logo</h2>
          <LogoPanel upload={uploadLogo} remove={removeLogo} hasLogo={branding.has_logo} />
        </Card>
      </div>
    </>
  ); // prettier-ignore
}

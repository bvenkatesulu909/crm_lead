import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { QuoteForm } from "@/components/quote-form";
import { Card, Forbidden, PageHeader } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type { Account, Quote } from "@/lib/api-types";
import { initialFormState } from "@/lib/form-state";
import { canReadContacts, canWriteQuotes } from "@/lib/permissions";
import { quoteNumber } from "@/lib/quotes";
import { apiFetch, getMe } from "@/lib/server/api";
import {
  approvalLimitOption,
  contactOptions,
  dealOptions,
  priceBookOptions,
} from "@/lib/server/options";

import { updateQuote } from "../../actions";

export const metadata: Metadata = { title: "Edit quote" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function EditQuotePage({
  params,
}: PageProps<"/quotes/[id]/edit">) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const [me, approvalLimit] = await Promise.all([
    getMe(),
    approvalLimitOption(),
  ]);
  if (!canWriteQuotes(me)) return <Forbidden />;
  let quote: Quote;
  try {
    quote = await apiFetch<Quote>(`/quotes/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
  if (quote.status !== "draft")
    return (
      <Forbidden message="Only draft quotes can be changed. Revise the quote to change it." />
    );
  const [account, { books, prices }, deals, contacts] = await Promise.all([
    apiFetch<Account>(`/accounts/${quote.account_id}`).catch(() => null),
    priceBookOptions(),
    dealOptions().catch(() => []),
    canReadContacts(me)
      ? contactOptions().catch(() => [])
      : Promise.resolve([]),
  ]);

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href={`/quotes/${quote.id}`} className="font-medium text-brand-700 hover:underline">
          ← {quoteNumber(quote.number, quote.revision)}
        </Link>
      </nav>
      <PageHeader title="Edit quote" description={quote.title} />
      <Card className="max-w-5xl p-6">
        <QuoteForm
          action={updateQuote.bind(null, quote.id, quote.version)}
          initialState={initialFormState}
          quote={quote}
          accounts={[{ id: quote.account_id, name: account?.name ?? "Account" }]}
          books={books}
          prices={prices}
          opportunities={deals}
          contacts={contacts}
          defaults={{ validUntil: quote.valid_until }}
          cancelHref={`/quotes/${quote.id}`}
          approvalLimit={approvalLimit}
          submitLabel="Save changes"
        />
      </Card>
    </>
  ); // prettier-ignore
}

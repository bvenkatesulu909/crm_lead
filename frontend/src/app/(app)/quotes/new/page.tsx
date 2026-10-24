import type { Metadata } from "next";

import { QuoteForm } from "@/components/quote-form";
import { Card, ErrorAlert, Forbidden, PageHeader } from "@/components/ui";
import { toErrorInfo } from "@/lib/api-error";
import { initialFormState } from "@/lib/form-state";
import { defaultValidUntil } from "@/lib/quotes";
import { canReadContacts, canWriteQuotes } from "@/lib/permissions";
import { getMe } from "@/lib/server/api";
import {
  accountOption,
  approvalLimitOption,
  contactOptions,
  dealOptions,
  priceBookOptions,
} from "@/lib/server/options";

import { createQuote } from "../actions";

export const metadata: Metadata = { title: "New quote" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function NewQuotePage({
  searchParams,
}: PageProps<"/quotes/new">) {
  const { account, opportunity } = await searchParams;
  const [me, approvalLimit] = await Promise.all([
    getMe(),
    approvalLimitOption(),
  ]);
  if (!canWriteQuotes(me)) return <Forbidden />;
  let data;
  try {
    data = await Promise.all([
      accountOption(account),
      priceBookOptions(),
      dealOptions().catch(() => []),
      canReadContacts(me)
        ? contactOptions().catch(() => [])
        : Promise.resolve([]),
    ]);
  } catch (error) {
    return (
      <ErrorAlert
        title="The quote form could not be loaded"
        error={toErrorInfo(error)}
      />
    );
  }
  const [defaultAccount, { books, prices }, deals, contacts] = data;
  const id = (v: string | string[] | undefined) =>
    typeof v === "string" && UUID.test(v) ? v : undefined;
  const validUntil = defaultValidUntil();
  const back = id(opportunity)
    ? `/opportunities/${id(opportunity)}`
    : id(account)
      ? `/accounts/${id(account)}`
      : "/quotes";

  return (
    <>
      <PageHeader title="New quote" description="Prices come from the price book; you choose products, quantities and discounts." />
      {books.length === 0 ? (
        <Card className="p-6 text-sm text-slate-700">
          There is no active price book yet. A manager can create one under Products → Price books.
        </Card>
      ) : (
        <Card className="max-w-5xl p-6">
          <QuoteForm
            action={createQuote}
            initialState={initialFormState}
            accounts={[]}
            searchAccounts
            defaultAccount={defaultAccount}
            books={books}
            prices={prices}
            opportunities={deals}
            contacts={contacts}
            defaults={{ accountId: id(account), opportunityId: id(opportunity), validUntil }}
            cancelHref={back}
            approvalLimit={approvalLimit}
            submitLabel="Create quote"
          />
        </Card>
      )}
    </>
  ); // prettier-ignore
}

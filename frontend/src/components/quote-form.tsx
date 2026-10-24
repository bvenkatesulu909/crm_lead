"use client";

import Link from "next/link";
import { useActionState, useState } from "react";

import { DialogField } from "@/components/action-dialog";
import { AccountPicker } from "@/components/account-picker";
import { ErrorAlert, buttonClass, cx } from "@/components/ui";
import type { Price, PriceBook, Quote } from "@/lib/api-types";
import { formatAmounts } from "@/lib/dashboard";
import type { FormState } from "@/lib/form-state";
import { previewTotals } from "@/lib/quotes";
import { useAccountLinks } from "@/lib/use-account-links";

type Option = { id: string; name: string; accountId?: string | null };
type Line = { product_id: string; quantity: string; discount_percent: string };

const money = (amount: number, currency: string) =>
  formatAmounts([{ currency, amount: amount.toFixed(2) }]);

/**
 * Create or edit a quote. Prices are NOT entered here: each product's price comes from the
 * chosen price book (the totals shown are a preview; the server calculates the real ones).
 */
export function QuoteForm({
  action,
  initialState,
  quote,
  accounts,
  books,
  prices,
  opportunities,
  contacts,
  defaults,
  searchAccounts = false,
  defaultAccount,
  cancelHref,
  submitLabel,
  approvalLimit,
}: {
  action: (state: FormState, formData: FormData) => Promise<FormState>;
  initialState: FormState;
  quote?: Quote;
  accounts: Option[];
  books: PriceBook[];
  /** Prices per price book id. */
  prices: Record<string, Price[]>;
  opportunities: Option[];
  contacts: Option[];
  defaults: { accountId?: string; opportunityId?: string; validUntil: string };
  /** Create: search accounts by name as the user types instead of choosing from a fixed list. */
  searchAccounts?: boolean;
  /** With searchAccounts: the account to show as chosen when the form opens. */
  defaultAccount?: { id: string; name: string } | null;
  cancelHref: string;
  submitLabel: string;
  /** The organisation's limit: line discounts above it need a manager's approval. */
  approvalLimit: number;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const v = state.values;
  const e = state.fieldErrors;
  const [accountId, setAccountId] = useState(
    v.account_id ?? quote?.account_id ?? defaults.accountId ?? "",
  );
  // With the account search, the chosen account's contacts and open deals come from the server.
  const links = useAccountLinks(accountId, searchAccounts);
  const forAccount = (own: Option[], fetched: Option[]) => [
    ...own.filter((o) => o.accountId === accountId),
    ...fetched.filter((f) => !own.some((o) => o.id === f.id)),
  ];
  const dealChoices = forAccount(opportunities, links.opportunities);
  const contactChoices = forAccount(contacts, links.contacts);
  const defaultBook = books.find((b) => b.is_default) ?? books[0];
  const [bookId, setBookId] = useState(
    v.price_book_id ?? quote?.price_book_id ?? defaultBook?.id ?? "",
  );
  const initialLines: Line[] = v.lines_json
    ? (JSON.parse(v.lines_json) as Line[])
    : (quote?.lines.map((l) => ({
        product_id: l.product_id,
        quantity: l.quantity,
        discount_percent: l.discount_percent,
      })) ?? []);
  const [lines, setLines] = useState<Line[]>(initialLines);
  const book = books.find((b) => b.id === bookId);
  const catalogue = (prices[bookId] ?? []).filter((p) => p.product_active);
  const priceOf = (id: string) => catalogue.find((p) => p.product_id === id);
  const preview = previewTotals(
    lines
      .filter((l) => priceOf(l.product_id))
      .map((l) => ({
        quantity: Number(l.quantity) || 0,
        listPrice: Number(priceOf(l.product_id)?.unit_price ?? 0),
        discountPercent: Number(l.discount_percent) || 0,
        taxRate: Number(priceOf(l.product_id)?.tax_rate ?? 0),
      })),
    approvalLimit,
  );
  const currency = book?.currency ?? "EUR";
  const set = (index: number, change: Partial<Line>) =>
    setLines(lines.map((l, i) => (i === index ? { ...l, ...change } : l)));
  const count = Object.keys(e).length;

  return (
    <form key={state.attempt} action={formAction} noValidate className="space-y-6">
      {state.error && <ErrorAlert title="The quote could not be saved" error={state.error} />}
      {count > 0 && (
        <div role="alert" className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          Please correct: {Object.values(e).join(" ")}
        </div>
      )}
      <div className="grid gap-5 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <DialogField id="quote-title" label="Title" error={e.title} hint="e.g. 50 widgets with installation">
            {(p) => <input name="title" maxLength={200} defaultValue={v.title ?? quote?.title} {...p} />}
          </DialogField>
        </div>
        {quote ? (
          <div>
            <p className="text-sm font-medium text-slate-700">Account</p>
            <p className="mt-2 text-sm">{accounts.find((a) => a.id === accountId)?.name ?? "Account"}</p>
            <input type="hidden" name="account_id" value={accountId} />
          </div>
        ) : (
          <DialogField id="quote-account" label="Account" error={e.account_id}>
            {(p) => searchAccounts ? (
              <AccountPicker
                {...p}
                defaultAccount={v.account_id && v.account_label ? { id: v.account_id, name: v.account_label } : defaultAccount}
                onChange={(account) => setAccountId(account?.id ?? "")}
              />
            ) : (
              <select name="account_id" value={accountId} onChange={(ev) => setAccountId(ev.target.value)} {...p}>
                <option value="">Choose an account…</option>
                {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            )}
          </DialogField>
        )}
        <DialogField id="quote-book" label="Price book" error={e.price_book_id} hint="Prices and currency come from here.">
          {(p) => (
            <select name="price_book_id" value={bookId} onChange={(ev) => setBookId(ev.target.value)} {...p}>
              {books.map((b) => <option key={b.id} value={b.id}>{b.name} ({b.currency})</option>)}
            </select>
          )}
        </DialogField>
        <DialogField id="quote-deal" label="Deal" optional error={e.opportunity_id}>
          {(p) => (
            <select name="opportunity_id" key={`${accountId}-${dealChoices.length}`} defaultValue={v.opportunity_id ?? quote?.opportunity_id ?? defaults.opportunityId ?? ""} {...p}>
              <option value="">None</option>
              {dealChoices.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          )}
        </DialogField>
        <DialogField id="quote-contact" label="For (contact)" optional error={e.contact_id}>
          {(p) => (
            <select name="contact_id" key={`${accountId}-${contactChoices.length}`} defaultValue={v.contact_id ?? quote?.contact_id ?? ""} {...p}>
              <option value="">None</option>
              {contactChoices.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          )}
        </DialogField>
        <DialogField id="quote-valid" label="Valid until" error={e.valid_until}>
          {(p) => <input type="date" name="valid_until" defaultValue={v.valid_until ?? quote?.valid_until ?? defaults.validUntil} {...p} />}
        </DialogField>
      </div>

      <fieldset>
        <legend className="mb-2 text-sm font-semibold text-slate-900">Lines</legend>
        {e.lines && <p className="mb-2 text-sm text-red-700">{e.lines}</p>}
        <div className="overflow-x-auto rounded-lg ring-1 ring-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs font-semibold uppercase text-slate-600">
              <tr>
                <th scope="col" className="px-3 py-2">Product</th>
                <th scope="col" className="px-3 py-2 text-right">List price</th>
                <th scope="col" className="px-3 py-2">Quantity</th>
                <th scope="col" className="px-3 py-2">Discount %</th>
                <th scope="col" className="px-3 py-2"><span className="sr-only">Remove</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {lines.map((line, i) => {
                const price = priceOf(line.product_id);
                const over = Number(line.discount_percent) > approvalLimit;
                return (
                  <tr key={i}>
                    <td className="px-3 py-2">
                      <select aria-label={`Line ${i + 1} product`} value={line.product_id} onChange={(ev) => set(i, { product_id: ev.target.value })}
                        className="w-56 rounded-md border-0 px-2 py-1 ring-1 ring-inset ring-slate-300">
                        <option value="">Choose…</option>
                        {catalogue.map((p) => <option key={p.product_id} value={p.product_id}>{p.sku} – {p.name}</option>)}
                      </select>
                      {line.product_id && !price && <p className="text-xs text-red-700">Not in this price book</p>}
                    </td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">{price ? `${money(Number(price.unit_price), currency)} / ${price.unit}` : "—"}</td>
                    <td className="px-3 py-2">
                      <input aria-label={`Line ${i + 1} quantity`} inputMode="decimal" value={line.quantity} onChange={(ev) => set(i, { quantity: ev.target.value })}
                        className="w-24 rounded-md border-0 px-2 py-1 ring-1 ring-inset ring-slate-300" />
                    </td>
                    <td className="px-3 py-2">
                      <input aria-label={`Line ${i + 1} discount`} inputMode="decimal" value={line.discount_percent} onChange={(ev) => set(i, { discount_percent: ev.target.value })}
                        className={cx("w-20 rounded-md border-0 px-2 py-1 ring-1 ring-inset", over ? "ring-amber-400" : "ring-slate-300")} />
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button type="button" onClick={() => setLines(lines.filter((_, j) => j !== i))} className="text-sm text-red-700 hover:underline">
                        Remove<span className="sr-only"> line {i + 1}</span>
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <button type="button" className={cx(buttonClass("secondary"), "mt-3")}
          onClick={() => setLines([...lines, { product_id: "", quantity: "1", discount_percent: "0" }])}>
          Add line
        </button>
        <input type="hidden" name="lines_json" value={JSON.stringify(lines)} />
      </fieldset>

      <dl className="ml-auto max-w-xs space-y-1 text-sm" aria-label="Totals preview">
        <div className="flex justify-between"><dt>List value</dt><dd>{money(preview.gross, currency)}</dd></div>
        <div className="flex justify-between"><dt>Discount</dt><dd>− {money(preview.discount, currency)}</dd></div>
        <div className="flex justify-between"><dt>Net</dt><dd>{money(preview.subtotal, currency)}</dd></div>
        <div className="flex justify-between"><dt>Tax</dt><dd>{money(preview.tax, currency)}</dd></div>
        <div className="flex justify-between border-t border-slate-200 pt-1 font-semibold"><dt>Total</dt><dd>{money(preview.total, currency)}</dd></div>
        {preview.needsApproval && (
          <p className="pt-2 text-xs text-amber-800">A discount above {approvalLimit} % needs a manager&apos;s approval before the quote can be sent.</p>
        )}
      </dl>

      <div className="grid gap-5 sm:grid-cols-2">
        <DialogField id="quote-customer-note" label="Note for the customer" optional error={e.customer_note} hint="Printed on the quote.">
          {(p) => <textarea name="customer_note" rows={3} maxLength={5000} defaultValue={v.customer_note ?? quote?.customer_note ?? ""} {...p} />}
        </DialogField>
        <DialogField id="quote-internal-note" label="Internal note" optional error={e.internal_note} hint="Staff only, never shown to the customer.">
          {(p) => <textarea name="internal_note" rows={3} maxLength={5000} defaultValue={v.internal_note ?? quote?.internal_note ?? ""} {...p} />}
        </DialogField>
      </div>
      <div className="flex justify-end gap-3 border-t border-slate-200 pt-5">
        <Link href={cancelHref} className={buttonClass("secondary")}>Cancel</Link>
        <button type="submit" disabled={pending} className={buttonClass("primary")}>{pending ? "Saving…" : submitLabel}</button>
      </div>
    </form>
  ); // prettier-ignore
}

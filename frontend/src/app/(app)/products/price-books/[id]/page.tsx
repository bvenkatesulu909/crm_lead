import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Card, EmptyState, Forbidden, SuccessAlert } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type { Price, PriceBook, ProductPage } from "@/lib/api-types";
import { taxLabel } from "@/lib/catalog";
import { formatAmounts } from "@/lib/dashboard";
import { canManageCatalog } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { removePrice, setPrice, updatePriceBook } from "../../actions";
import {
  EditPriceBookDialog,
  RemovePriceDialog,
  SetPriceDialog,
} from "../../catalog-dialogs";

export const metadata: Metadata = { title: "Price book" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DONE: Record<string, string> = {
  created: "The price book was created. Add prices for your products.",
  updated: "The price book was saved.",
  "price-set": "The price was saved.",
  "price-removed": "The product was removed from this price book.",
};

export default async function PriceBookPage({
  params,
  searchParams,
}: PageProps<"/products/price-books/[id]">) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  if (!UUID.test(id)) notFound();
  const me = await getMe();
  const manager = canManageCatalog(me);
  let book: PriceBook;
  let prices: Price[];
  try {
    [book, prices] = await Promise.all([
      apiFetch<PriceBook>(`/price-books/${id}`),
      apiFetch<Price[]>(`/price-books/${id}/prices`),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    throw error;
  }
  // Only managers can add prices, so only they need the list of products without one.
  const missing = manager
    ? ((
        await apiFetch<ProductPage>("/products?active=true&limit=500").catch(
          () => null,
        )
      )?.items
        .filter((p) => !prices.some((x) => x.product_id === p.id))
        .map((p) => ({ id: p.id, label: `${p.sku} – ${p.name}` })) ?? [])
    : [];
  const done = typeof query.done === "string" ? DONE[query.done] : undefined;

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/products" className="font-medium text-brand-700 hover:underline">← Products</Link>
      </nav>
      {done && <div className="mb-4"><SuccessAlert>{done}</SuccessAlert></div>}
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm text-slate-500">Price book · {book.currency}</p>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{book.name}</h1>
          <p className="mt-2 flex flex-wrap gap-2 text-xs">
            {book.is_default && <span className="rounded-full bg-brand-50 px-2 py-0.5 text-brand-800">Default for {book.currency}</span>}
            {!book.is_active && <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">Inactive</span>}
          </p>
          {book.description && <p className="mt-2 text-sm text-slate-600">{book.description}</p>}
        </div>
        {manager && (
          <div className="flex flex-wrap gap-2">
            {missing.length > 0 && <SetPriceDialog action={setPrice.bind(null, book.id, null)} currency={book.currency} products={missing} />}
            <EditPriceBookDialog key={book.version} action={updatePriceBook.bind(null, book.id, book.version)} book={book} />
          </div>
        )}
      </div>

      <Card>
        {prices.length === 0 ? (
          <EmptyState title="No prices yet" description={manager ? "Add a price for each product you want to quote in this book." : "Ask a manager to add prices."} />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <caption className="sr-only">Prices in {book.name}</caption>
              <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
                <tr>
                  <th scope="col" className="px-5 py-3">Product</th>
                  <th scope="col" className="px-5 py-3">Unit</th>
                  <th scope="col" className="px-5 py-3 text-right">Tax</th>
                  <th scope="col" className="px-5 py-3 text-right">Unit price</th>
                  {manager && <th scope="col" className="px-5 py-3"><span className="sr-only">Actions</span></th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {prices.map((p) => (
                  <tr key={p.product_id}>
                    <th scope="row" className="px-5 py-3 text-left font-medium">
                      <Link href={`/products/${p.product_id}`} className="text-brand-700 hover:underline">
                        <span className="font-mono text-xs text-slate-500">{p.sku}</span> {p.name}
                      </Link>
                      {!p.product_active && <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">Inactive</span>}
                    </th>
                    <td className="px-5 py-3 text-slate-700">{p.unit}</td>
                    <td className="px-5 py-3 text-right text-slate-700">{taxLabel(p.tax_rate)}</td>
                    <td className="px-5 py-3 text-right font-medium whitespace-nowrap">{formatAmounts([{ currency: p.currency, amount: p.unit_price }])}</td>
                    {manager && (
                      <td className="px-5 py-3">
                        <div className="flex justify-end gap-2">
                          <SetPriceDialog action={setPrice.bind(null, book.id, p.product_id)} currency={book.currency} product={{ name: p.name, price: p.unit_price }} />
                          <RemovePriceDialog action={removePrice.bind(null, book.id, p.product_id)} name={p.name} />
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  ); // prettier-ignore
}

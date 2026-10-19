import type { Metadata } from "next";
import Link from "next/link";

import { Pagination } from "@/components/pagination";
import {
  ButtonLink,
  Card,
  EmptyState,
  ErrorAlert,
  Forbidden,
  PageHeader,
  buttonClass,
} from "@/components/ui";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import type { PriceBook, ProductPage } from "@/lib/api-types";
import { PRODUCT_TYPE_LABELS, taxLabel } from "@/lib/catalog";
import { canManageCatalog } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { createPriceBook } from "./actions";
import { NewPriceBookDialog } from "./catalog-dialogs";

export const metadata: Metadata = { title: "Products" };

const PAGE_SIZE = 50;
const field =
  "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600";
const ACTIVE = { active: "true", inactive: "false" } as const;

export default async function ProductsPage({
  searchParams,
}: PageProps<"/products">) {
  const raw = await searchParams;
  const one = (v: string | string[] | undefined) =>
    (Array.isArray(v) ? v[0] : v) ?? "";
  const q = one(raw.q).trim().slice(0, 100);
  const show =
    one(raw.show) in ACTIVE ? (one(raw.show) as keyof typeof ACTIVE) : "";
  const pageNumber = Math.min(
    Math.max(Number.parseInt(one(raw.page), 10) || 1, 1),
    2000,
  );
  const me = await getMe();
  const manager = canManageCatalog(me);
  const query = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String((pageNumber - 1) * PAGE_SIZE),
  });
  if (q) query.set("q", q);
  if (show) query.set("active", ACTIVE[show]);

  let data: ProductPage;
  let books: PriceBook[];
  try {
    [data, books] = await Promise.all([
      apiFetch<ProductPage>(`/products?${query}`),
      apiFetch<PriceBook[]>("/price-books"),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    return (
      <ErrorAlert
        title="Products could not be loaded"
        error={toErrorInfo(error)}
      />
    );
  }
  const href = (page: number) => {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (show) p.set("show", show);
    if (page > 1) p.set("page", String(page));
    return p.toString() ? `/products?${p}` : "/products";
  };

  return (
    <>
      <PageHeader
        title="Products"
        description="What you sell, and the price books quotes take their prices from."
        actions={manager && <ButtonLink href="/products/new">New product</ButtonLink>}
      />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <form role="search" aria-label="Filter products" className="grid gap-4 px-5 py-4 sm:grid-cols-[2fr_1fr_auto]">
            <div>
              <label htmlFor="product-q" className="text-sm font-medium text-slate-700">Search</label>
              <input id="product-q" name="q" type="search" defaultValue={q} maxLength={100} placeholder="Name or code" className={field} />
            </div>
            <div>
              <label htmlFor="product-show" className="text-sm font-medium text-slate-700">Show</label>
              <select id="product-show" name="show" defaultValue={show} className={field}>
                <option value="">All</option>
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
              </select>
            </div>
            <div className="flex items-end gap-2">
              <button type="submit" className={buttonClass("primary")}>Apply</button>
              {(q || show) && <Link href="/products" className={buttonClass("secondary")}>Clear</Link>}
            </div>
          </form>
          <div className="border-t border-slate-200">
            {data.items.length === 0 ? (
              <EmptyState title="No products found" description={manager ? "Add your first product, then give it a price in a price book." : "Ask a manager to add products."} />
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-slate-200 text-sm">
                  <caption className="sr-only">Products, page {pageNumber}</caption>
                  <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
                    <tr>
                      <th scope="col" className="px-5 py-3">Product</th>
                      <th scope="col" className="px-5 py-3">Type</th>
                      <th scope="col" className="px-5 py-3">Unit</th>
                      <th scope="col" className="px-5 py-3 text-right">Tax</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 bg-white">
                    {data.items.map((p) => (
                      <tr key={p.id}>
                        <th scope="row" className="px-5 py-3 text-left font-medium">
                          <Link href={`/products/${p.id}`} className="text-brand-700 hover:underline">
                            <span className="font-mono text-xs text-slate-500">{p.sku}</span> {p.name}
                          </Link>
                          {!p.is_active && <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">Inactive</span>}
                        </th>
                        <td className="px-5 py-3 text-slate-700">{PRODUCT_TYPE_LABELS[p.product_type]}</td>
                        <td className="px-5 py-3 text-slate-700">{p.unit}</td>
                        <td className="px-5 py-3 text-right text-slate-700">{taxLabel(p.tax_rate)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          {data.total > 0 && (
            <div className="border-t border-slate-200">
              <Pagination total={data.total} page={pageNumber} pageSize={PAGE_SIZE} hrefForPage={href} />
            </div>
          )}
        </Card>

        <Card aria-labelledby="books-heading" className="self-start">
          <div className="flex items-center justify-between gap-2 border-b border-slate-200 px-5 py-4">
            <h2 id="books-heading" className="text-base font-semibold text-slate-900">Price books</h2>
            {manager && <NewPriceBookDialog action={createPriceBook} />}
          </div>
          {books.length === 0 ? (
            <p className="px-5 py-4 text-sm text-slate-600">No price books yet.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {books.map((b) => (
                <li key={b.id} className="px-5 py-3 text-sm">
                  <Link href={`/products/price-books/${b.id}`} className="font-medium text-brand-700 hover:underline">{b.name}</Link>
                  <span className="ml-2 text-slate-500">{b.currency}</span>
                  {b.is_default && <span className="ml-2 rounded-full bg-brand-50 px-2 py-0.5 text-xs text-brand-800">Default</span>}
                  {!b.is_active && <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">Inactive</span>}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  ); // prettier-ignore
}

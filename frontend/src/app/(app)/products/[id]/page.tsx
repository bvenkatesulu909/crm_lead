import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ProductForm } from "@/components/product-form";
import { Card, Forbidden, SuccessAlert } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type { Price, PriceBook, Product } from "@/lib/api-types";
import { PRODUCT_TYPE_LABELS, taxLabel } from "@/lib/catalog";
import { formatAmounts } from "@/lib/dashboard";
import { initialFormState } from "@/lib/form-state";
import { canManageCatalog } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { setProductActive, updateProduct } from "../actions";
import { ProductActiveDialog } from "../catalog-dialogs";

export const metadata: Metadata = { title: "Product" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DONE: Record<string, string> = {
  created: "The product was created. Now give it a price in a price book.",
  updated: "The product was saved.",
  activated: "The product is active again.",
  deactivated: "The product was deactivated.",
};

export default async function ProductPage({
  params,
  searchParams,
}: PageProps<"/products/[id]">) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  if (!UUID.test(id)) notFound();
  const me = await getMe();
  let product: Product;
  let books: PriceBook[];
  try {
    [product, books] = await Promise.all([
      apiFetch<Product>(`/products/${id}`),
      apiFetch<PriceBook[]>("/price-books"),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    throw error;
  }
  // Price books are few, so one request per book is fine here.
  const prices = await Promise.all(
    books.map(async (book) => ({
      book,
      price: (
        await apiFetch<Price[]>(`/price-books/${book.id}/prices`).catch(
          () => [],
        )
      ).find((p) => p.product_id === product.id),
    })),
  );
  const done = typeof query.done === "string" ? DONE[query.done] : undefined;
  const manager = canManageCatalog(me);

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/products" className="font-medium text-brand-700 hover:underline">← Products</Link>
      </nav>
      {done && <div className="mb-4"><SuccessAlert>{done}</SuccessAlert></div>}
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-mono text-sm text-slate-500">{product.sku}</p>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{product.name}</h1>
          <p className="mt-1 text-sm text-slate-600">
            {PRODUCT_TYPE_LABELS[product.product_type]} · per {product.unit} · tax {taxLabel(product.tax_rate)}
            {!product.is_active && <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">Inactive</span>}
          </p>
        </div>
        {manager && (
          <ProductActiveDialog
            key={product.version}
            active={product.is_active}
            action={setProductActive.bind(null, product.id, product.version, !product.is_active)}
          />
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          {product.description && (
            <Card className="p-5 text-sm">
              <h2 className="font-semibold text-slate-900">Description</h2>
              <p className="mt-1 whitespace-pre-line text-slate-700">{product.description}</p>
            </Card>
          )}
          {manager && (
            <Card className="p-6">
              <h2 className="mb-4 text-base font-semibold text-slate-900">Edit product</h2>
              <ProductForm
                key={product.version}
                action={updateProduct.bind(null, product.id, product.version)}
                initialState={initialFormState}
                product={product}
                cancelHref="/products"
                submitLabel="Save changes"
              />
            </Card>
          )}
        </div>
        <Card aria-labelledby="prices-heading" className="self-start">
          <h2 id="prices-heading" className="border-b border-slate-200 px-5 py-4 text-base font-semibold text-slate-900">Prices</h2>
          <ul className="divide-y divide-slate-100">
            {prices.map(({ book, price }) => (
              <li key={book.id} className="flex justify-between gap-3 px-5 py-3 text-sm">
                <Link href={`/products/price-books/${book.id}`} className="text-brand-700 hover:underline">{book.name}</Link>
                <span className={price ? "font-medium" : "text-slate-500"}>
                  {price ? formatAmounts([{ currency: price.currency, amount: price.unit_price }]) : "No price"}
                </span>
              </li>
            ))}
            {prices.length === 0 && <li className="px-5 py-3 text-sm text-slate-600">No price books yet.</li>}
          </ul>
        </Card>
      </div>
    </>
  ); // prettier-ignore
}

import type { Metadata } from "next";
import Link from "next/link";

import { ProductForm } from "@/components/product-form";
import { Card, Forbidden, PageHeader } from "@/components/ui";
import { initialFormState } from "@/lib/form-state";
import { canManageCatalog } from "@/lib/permissions";
import { getMe } from "@/lib/server/api";

import { createProduct } from "../actions";

export const metadata: Metadata = { title: "New product" };

export default async function NewProductPage() {
  const me = await getMe();
  if (!canManageCatalog(me)) return <Forbidden />;
  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link href="/products" className="font-medium text-brand-700 hover:underline">← Products</Link>
      </nav>
      <PageHeader title="New product" description="After saving, give the product a price in a price book so it can be quoted." />
      <Card className="p-6">
        <ProductForm action={createProduct} initialState={initialFormState} cancelHref="/products" submitLabel="Create product" />
      </Card>
    </>
  ); // prettier-ignore
}

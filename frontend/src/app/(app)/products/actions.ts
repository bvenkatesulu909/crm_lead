"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { toErrorInfo } from "@/lib/api-error";
import type { PriceBook, Product } from "@/lib/api-types";
import type { DialogState } from "@/lib/dialog-state";
import type { FormState } from "@/lib/form-state";
import { apiFetch } from "@/lib/server/api";
import {
  fieldErrors,
  priceBookSchema,
  priceSchema,
  productSchema,
} from "@/lib/validation/catalog";

/**
 * Catalogue Server Actions (products, price books, prices). Only managers may change the
 * catalogue - the API enforces that; IDs and versions from the browser are re-checked there.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const checkedId = (id: string) => {
  if (!UUID.test(id)) throw new Error("invalid id");
  return id;
};
const version = (v: number) => {
  if (!Number.isInteger(v) || v < 1) throw new Error("invalid version");
  return v;
};
const text = (fd: FormData, name: string) => String(fd.get(name) ?? "");

const PRODUCT_FIELDS = [
  "sku",
  "name",
  "description",
  "product_type",
  "unit",
  "tax_rate",
] as const;
const readProduct = (fd: FormData) =>
  Object.fromEntries(PRODUCT_FIELDS.map((f) => [f, text(fd, f)])) as Record<
    (typeof PRODUCT_FIELDS)[number],
    string
  >;

export async function createProduct(
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const values = readProduct(formData);
  const attempt = previous.attempt + 1;
  const parsed = productSchema.safeParse(values);
  if (!parsed.success)
    return {
      attempt,
      values,
      fieldErrors: fieldErrors(parsed.error),
      error: null,
    };
  let product: Product;
  try {
    product = await apiFetch<Product>("/products", {
      method: "POST",
      body: JSON.stringify(parsed.data),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return { attempt, values, fieldErrors: info.fieldErrors, error: info };
  }
  redirect(`/products/${product.id}?done=created`);
}

export async function updateProduct(
  productId: string,
  currentVersion: number,
  previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const path = `/products/${checkedId(productId)}`;
  const values = readProduct(formData);
  const attempt = previous.attempt + 1;
  const parsed = productSchema.safeParse(values);
  if (!parsed.success)
    return {
      attempt,
      values,
      fieldErrors: fieldErrors(parsed.error),
      error: null,
    };
  try {
    await apiFetch(path, {
      method: "PATCH",
      body: JSON.stringify({
        version: version(currentVersion),
        ...parsed.data,
      }),
    });
  } catch (error) {
    const info = toErrorInfo(error);
    return { attempt, values, fieldErrors: info.fieldErrors, error: info };
  }
  redirect(`${path}?done=updated`);
}

const failed = (previous: DialogState, error: unknown): DialogState => {
  const info = toErrorInfo(error);
  return {
    attempt: previous.attempt + 1,
    fieldErrors: info.fieldErrors,
    error: info,
  };
};

/** Activate or deactivate a product (inactive products can't be added to quotes). */
export async function setProductActive(
  productId: string,
  currentVersion: number,
  active: boolean,
  previous: DialogState,
): Promise<DialogState> {
  const path = `/products/${checkedId(productId)}`;
  try {
    await apiFetch(path, {
      method: "PATCH",
      body: JSON.stringify({
        version: version(currentVersion),
        is_active: active,
      }),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect(`${path}?done=${active ? "activated" : "deactivated"}`);
}

export async function createPriceBook(
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const parsed = priceBookSchema.safeParse({
    name: text(formData, "name"),
    currency: text(formData, "currency"),
    description: text(formData, "description"),
    is_default: formData.get("is_default") === "on",
  });
  if (!parsed.success)
    return {
      attempt: previous.attempt + 1,
      fieldErrors: fieldErrors(parsed.error),
      error: null,
    };
  let book: PriceBook;
  try {
    book = await apiFetch<PriceBook>("/price-books", {
      method: "POST",
      body: JSON.stringify(parsed.data),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect(`/products/price-books/${book.id}?done=created`);
}

/** Rename a price book, make it the default for its currency, or (de)activate it. */
export async function updatePriceBook(
  bookId: string,
  currentVersion: number,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const path = `/price-books/${checkedId(bookId)}`;
  const parsed = priceBookSchema
    .pick({ name: true, description: true, is_default: true })
    .safeParse({
      name: text(formData, "name"),
      description: text(formData, "description"),
      is_default: formData.get("is_default") === "on",
    });
  if (!parsed.success)
    return {
      attempt: previous.attempt + 1,
      fieldErrors: fieldErrors(parsed.error),
      error: null,
    };
  try {
    await apiFetch(path, {
      method: "PATCH",
      body: JSON.stringify({
        version: version(currentVersion),
        ...parsed.data,
        is_active: formData.get("is_active") === "on",
      }),
    });
  } catch (error) {
    return failed(previous, error);
  }
  redirect(`/products${path}?done=updated`);
}

/** Set (add or change) the price of one product in a price book. */
export async function setPrice(
  bookId: string,
  fixedProductId: string | null,
  previous: DialogState,
  formData: FormData,
): Promise<DialogState> {
  const book = checkedId(bookId);
  const productId = fixedProductId ?? text(formData, "product_id");
  if (!UUID.test(productId))
    return {
      attempt: previous.attempt + 1,
      fieldErrors: { product_id: "Choose a product." },
      error: null,
    };
  const parsed = priceSchema.safeParse({
    unit_price: text(formData, "unit_price"),
  });
  if (!parsed.success)
    return {
      attempt: previous.attempt + 1,
      fieldErrors: fieldErrors(parsed.error),
      error: null,
    };
  try {
    await apiFetch(`/price-books/${book}/prices/${productId}`, {
      method: "PUT",
      body: JSON.stringify(parsed.data),
    });
  } catch (error) {
    return failed(previous, error);
  }
  revalidatePath(`/products/price-books/${book}`);
  redirect(`/products/price-books/${book}?done=price-set`);
}

export async function removePrice(
  bookId: string,
  productId: string,
  previous: DialogState,
): Promise<DialogState> {
  const book = checkedId(bookId);
  try {
    await apiFetch(`/price-books/${book}/prices/${checkedId(productId)}`, {
      method: "DELETE",
    });
  } catch (error) {
    return failed(previous, error);
  }
  revalidatePath(`/products/price-books/${book}`);
  redirect(`/products/price-books/${book}?done=price-removed`);
}

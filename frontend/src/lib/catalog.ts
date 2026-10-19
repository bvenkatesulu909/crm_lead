import type { Product } from "@/lib/api-types";

export const PRODUCT_TYPE_LABELS: Record<Product["product_type"], string> = {
  product: "Product",
  service: "Service",
  subscription: "Subscription",
};

/** "19.00" → "19 %" - tax rates without trailing zeros. */
export const taxLabel = (rate: string) => `${Number(rate)} %`;

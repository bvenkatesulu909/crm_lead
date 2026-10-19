import type { Metadata } from "next";
import Link from "next/link";

import { PortalOrderList } from "@/components/orders";
import { Card, ErrorAlert } from "@/components/ui";
import { toErrorInfo } from "@/lib/api-error";
import type { PortalOrderSummary } from "@/lib/api-types";
import { apiFetch } from "@/lib/server/api";

export const metadata: Metadata = { title: "Orders" };

export default async function PortalOrdersPage() {
  let orders: PortalOrderSummary[];
  try {
    // The API returns only confirmed orders of this customer's own accounts.
    orders = await apiFetch<PortalOrderSummary[]>("/portal/orders?limit=100");
  } catch (error) {
    return (
      <ErrorAlert
        title="Your orders could not be loaded"
        error={toErrorInfo(error)}
      />
    );
  }

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link
          href="/portal"
          className="font-medium text-brand-700 hover:underline"
        >
          ← Portal home
        </Link>
      </nav>
      <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
        Orders
      </h1>
      <p className="mt-1 mb-6 text-sm text-slate-600">
        Your company&apos;s orders and where they are.
      </p>
      <Card>
        <PortalOrderList
          orders={orders}
          emptyText="No orders yet. Orders appear here as soon as we confirm them."
        />
      </Card>
    </>
  );
}

import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { OrderForm } from "@/components/order-form";
import { formatQuantity, orderNumber } from "@/components/orders";
import { Card, Forbidden, PageHeader } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type { Account, Order } from "@/lib/api-types";
import { initialFormState } from "@/lib/form-state";
import { canReadAccounts, canWriteOrders } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { updateOrder } from "../../actions";

export const metadata: Metadata = { title: "Edit order" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function EditOrderPage({
  params,
}: PageProps<"/orders/[id]/edit">) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const me = await getMe();
  if (!canWriteOrders(me)) return <Forbidden />;
  let order: Order;
  try {
    order = await apiFetch<Order>(`/orders/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
  // Confirmed orders are frozen; the API refuses edits as well.
  if (order.status !== "draft") redirect(`/orders/${id}`);
  const account = canReadAccounts(me)
    ? await apiFetch<Account>(`/accounts/${order.account_id}`).catch(() => null)
    : null;

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-4 text-sm">
        <Link
          href={`/orders/${id}`}
          className="font-medium text-brand-700 hover:underline"
        >
          ← {orderNumber(order.number)}
        </Link>
      </nav>
      <PageHeader
        title={`Edit ${orderNumber(order.number)}`}
        description="Draft orders can be changed until they are confirmed."
      />
      <Card className="max-w-4xl p-6">
        <OrderForm
          action={updateOrder.bind(null, order.id)}
          initialState={initialFormState}
          fixedAccountName={account?.name ?? "Customer account"}
          version={order.version}
          defaults={{
            currency: order.currency,
            customer_reference: order.customer_reference ?? "",
            expected_delivery_date: order.expected_delivery_date ?? "",
            internal_note: order.internal_note ?? "",
            lines: order.lines.map((l) => ({
              product_code: l.product_code ?? "",
              description: l.description,
              quantity: formatQuantity(l.quantity),
              unit_price: l.unit_price,
              tax_rate: formatQuantity(l.tax_rate),
            })),
          }}
          cancelHref={`/orders/${id}`}
          submitLabel="Save changes"
        />
      </Card>
    </>
  );
}

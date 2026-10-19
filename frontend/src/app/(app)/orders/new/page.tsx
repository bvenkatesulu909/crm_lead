import type { Metadata } from "next";

import { OrderForm } from "@/components/order-form";
import { Card, EmptyState, Forbidden, PageHeader } from "@/components/ui";
import type { AccountPage } from "@/lib/api-types";
import { initialFormState } from "@/lib/form-state";
import { canWriteOrders } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { createOrder } from "../actions";

export const metadata: Metadata = { title: "New order" };

export default async function NewOrderPage({
  searchParams,
}: PageProps<"/orders/new">) {
  const me = await getMe();
  if (!canWriteOrders(me)) return <Forbidden />;
  // Offered accounts are the ones this user can see; the API checks again on save
  // (sales agents may only order for accounts they own).
  const accounts = (await apiFetch<AccountPage>("/accounts?limit=200")).items;
  const accountParam = (await searchParams).account;

  return (
    <>
      <PageHeader
        title="New order"
        description="The order starts as a draft. Confirm it when the customer has agreed; then the customer sees it in their portal."
      />
      <Card className="max-w-4xl p-6">
        {accounts.length === 0 ? (
          <EmptyState
            title="No customer accounts"
            description="You need a customer account before you can create an order."
          />
        ) : (
          <OrderForm
            action={createOrder}
            initialState={initialFormState}
            accounts={accounts.map((a) => ({ id: a.id, name: a.name }))}
            defaultAccountId={
              typeof accountParam === "string" ? accountParam : undefined
            }
            defaults={{
              currency: "EUR",
              customer_reference: "",
              expected_delivery_date: "",
              internal_note: "",
              lines: [],
            }}
            cancelHref="/orders"
            submitLabel="Save draft"
          />
        )}
      </Card>
    </>
  );
}

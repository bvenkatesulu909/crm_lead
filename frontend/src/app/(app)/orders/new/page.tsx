import type { Metadata } from "next";

import { OrderForm } from "@/components/order-form";
import { Card, EmptyState, Forbidden, PageHeader } from "@/components/ui";
import type { AccountPage } from "@/lib/api-types";
import { initialFormState } from "@/lib/form-state";
import { canWriteOrders } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";
import { accountOption } from "@/lib/server/options";

import { createOrder } from "../actions";

export const metadata: Metadata = { title: "New order" };

export default async function NewOrderPage({
  searchParams,
}: PageProps<"/orders/new">) {
  const me = await getMe();
  if (!canWriteOrders(me)) return <Forbidden />;
  // The account field searches the accounts this user can see; the API checks again on save
  // (sales agents may only order for accounts they own).
  const hasAccounts = (await apiFetch<AccountPage>("/accounts?limit=1")).total > 0;
  const defaultAccount = await accountOption((await searchParams).account);

  return (
    <>
      <PageHeader
        title="New order"
        description="The order starts as a draft. Confirm it when the customer has agreed; then the customer sees it in their portal."
      />
      <Card className="max-w-4xl p-6">
        {!hasAccounts ? (
          <EmptyState
            title="No customer accounts"
            description="You need a customer account before you can create an order."
          />
        ) : (
          <OrderForm
            action={createOrder}
            initialState={initialFormState}
            accounts={[]}
            searchAccounts
            defaultAccount={defaultAccount}
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

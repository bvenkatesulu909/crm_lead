"use client";

import { useActionState, useState } from "react";

import { formatMoney } from "@/components/orders";
import { ErrorAlert, buttonClass } from "@/components/ui";
import { initialDialogState, type DialogState } from "@/lib/dialog-state";
import { formatDateTime } from "@/lib/format";
import {
  LINK_STATUS_TEXT,
  openLink,
  safePayUrl,
  type PaymentLink,
} from "@/lib/payment-links";

type CreateAction = (state: DialogState) => Promise<DialogState>;

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className={buttonClass("secondary")}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
        } catch {
          setCopied(false); // clipboard blocked: the address is shown above to copy by hand
        }
      }}
    >
      {copied ? "Copied" : "Copy link"}
    </button>
  );
}

/**
 * The staff view: the open link (address, amount, expiry), a button to create or replace it, and the
 * earlier links in one line each. The address is shown as plain text and opened only when it is a
 * plain https address.
 */
export function StaffPaymentLinks({
  links,
  currency,
  canCreate,
  action,
  now,
}: {
  links: PaymentLink[];
  currency: string;
  canCreate: boolean;
  action: CreateAction;
  now: Date;
}) {
  const [state, formAction, pending] = useActionState(
    action,
    initialDialogState,
  );
  const money = (value: string) => formatMoney(value, currency);
  const open = openLink(links, now);
  const address = open ? safePayUrl(open.short_url) : null;
  const earlier = links.filter((link) => link !== open);
  return (
    <div className="space-y-4">
      {state.error && (
        <ErrorAlert
          title="The payment link could not be created"
          error={state.error}
        />
      )}
      {open && address ? (
        <div className="space-y-2" data-testid="open-link">
          <p className="text-sm text-slate-700">
            Open link for{" "}
            <span className="font-medium">{money(open.amount)}</span>, valid
            until {formatDateTime(open.expires_at)}.
          </p>
          <p className="rounded-md bg-slate-50 p-2 font-mono text-xs break-all text-slate-800">
            {address}
          </p>
          <div className="flex flex-wrap gap-2">
            <a
              href={address}
              target="_blank"
              rel="noopener noreferrer"
              className={buttonClass("secondary")}
            >
              Open payment page
            </a>
            <CopyButton text={address} />
          </div>
        </div>
      ) : (
        <p className="text-sm text-slate-600">
          {links.length === 0
            ? "No payment link yet."
            : "There is no open payment link."}
        </p>
      )}
      {canCreate && (
        <form action={formAction}>
          <button
            type="submit"
            disabled={pending}
            className={buttonClass(open ? "secondary" : "primary")}
          >
            {pending
              ? "Creating…"
              : open
                ? "Create a new link (replaces this one)"
                : "Create UPI payment link"}
          </button>
        </form>
      )}
      <p className="text-xs text-slate-500">
        The buyer pays on Razorpay&apos;s page; the CRM never sees their UPI
        details. The payment appears under Payments within a few minutes of
        Razorpay confirming it.
      </p>
      {earlier.length > 0 && (
        <ul className="divide-y divide-slate-100 border-t border-slate-100 text-xs text-slate-600">
          {earlier.map((link) => (
            <li key={link.id} className="flex justify-between gap-3 py-2">
              <span>
                {money(link.amount)} · {formatDateTime(link.created_at)}
              </span>
              <span>
                {link.status === "created"
                  ? LINK_STATUS_TEXT.expired
                  : LINK_STATUS_TEXT[link.status]}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The customer's view: one button to the open link, with what will happen in plain words. */
export function PortalPayByUpi({ link }: { link: PaymentLink }) {
  const money = (value: string) => formatMoney(value, link.currency);
  const address = safePayUrl(link.short_url);
  if (!address) return null;
  return (
    <div
      role="note"
      className="mb-6 flex flex-col gap-3 rounded-md border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950 sm:flex-row sm:items-center sm:justify-between"
    >
      <p>
        <span className="font-medium">Pay {money(link.amount)} by UPI.</span>{" "}
        You will pay on Razorpay&apos;s secure page; we never see your UPI
        details. It can take a few minutes to show here afterwards.
      </p>
      <a
        href={address}
        target="_blank"
        rel="noopener noreferrer"
        className={buttonClass("primary")}
      >
        Pay by UPI
      </a>
    </div>
  );
}

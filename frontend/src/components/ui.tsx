import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

import type { ApiErrorInfo } from "@/lib/api-error";
import type { LeadStatus } from "@/lib/api-types";

/** Small shared building blocks so every screen looks and behaves the same. */

export function cx(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

const buttonStyles = {
  primary:
    "bg-brand-600 text-white hover:bg-brand-700 disabled:bg-brand-600/60",
  secondary:
    "bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50",
  danger: "bg-red-600 text-white hover:bg-red-700",
} as const;

export function buttonClass(variant: keyof typeof buttonStyles = "primary") {
  return cx(
    "inline-flex items-center justify-center gap-2 rounded-md px-3.5 py-2 text-sm font-semibold shadow-sm",
    "disabled:cursor-not-allowed",
    buttonStyles[variant],
  );
}

export function ButtonLink({
  variant = "primary",
  className,
  ...props
}: ComponentProps<typeof Link> & { variant?: keyof typeof buttonStyles }) {
  return <Link className={cx(buttonClass(variant), className)} {...props} />;
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
          {title}
        </h1>
        {description && (
          <p className="mt-1 text-sm text-slate-600">{description}</p>
        )}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </div>
  );
}

export function Card({ className, ...props }: ComponentProps<"section">) {
  return (
    <section
      className={cx(
        "rounded-lg bg-white shadow-sm ring-1 ring-slate-200",
        className,
      )}
      {...props}
    />
  );
}

const statusStyles: Record<LeadStatus, string> = {
  new: "bg-sky-50 text-sky-800 ring-sky-200",
  contacted: "bg-amber-50 text-amber-800 ring-amber-200",
  qualified: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  unqualified: "bg-slate-100 text-slate-700 ring-slate-300",
  converted: "bg-brand-50 text-brand-800 ring-brand-100",
};

export const STATUS_LABELS: Record<LeadStatus, string> = {
  new: "New",
  contacted: "Contacted",
  qualified: "Qualified",
  unqualified: "Unqualified",
  converted: "Converted",
};

export function StatusBadge({ status }: { status: LeadStatus }) {
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        statusStyles[status],
      )}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}

/** Shows a backend error in plain words, plus the request ID support can look up in the logs. */
export function ErrorAlert({
  error,
  title,
}: {
  error: ApiErrorInfo;
  title?: string;
}) {
  return (
    <div
      role="alert"
      className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800"
    >
      <p className="font-semibold">{title ?? "Something went wrong"}</p>
      <p className="mt-1">{error.message}</p>
      {error.requestId && (
        <p className="mt-2 text-xs text-red-700">
          Reference: <span className="font-mono">{error.requestId}</span>
        </p>
      )}
    </div>
  );
}

export function SuccessAlert({ children }: { children: ReactNode }) {
  return (
    <div
      role="status"
      className="rounded-md border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800"
    >
      {children}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
      <p className="text-base font-semibold text-slate-900">{title}</p>
      {description && (
        <p className="max-w-md text-sm text-slate-600">{description}</p>
      )}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

export function Forbidden({ message }: { message?: string }) {
  return (
    <Card className="p-6">
      <EmptyState
        title="You don't have access to this page"
        description={
          message ??
          "Your role doesn't include this part of the CRM. Ask your administrator if you need it."
        }
        action={
          <ButtonLink href="/" variant="secondary">
            Back to dashboard
          </ButtonLink>
        }
      />
    </Card>
  );
}

/** Active / inactive badge for customer accounts. */
export function AccountStatus({ status }: { status: string }) {
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        status === "active"
          ? "bg-emerald-50 text-emerald-800 ring-emerald-200"
          : "bg-slate-100 text-slate-700 ring-slate-300",
      )}
    >
      {status === "active" ? "Active" : "Inactive"}
    </span>
  );
}

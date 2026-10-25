"use client";

import Link from "next/link";
import { useActionState, useRef, useState, type FormEvent } from "react";

import { ErrorAlert, buttonClass, cx } from "@/components/ui";
import { LEAD_SOURCES, PROPERTY_TYPES } from "@/lib/api-types";
import { PROPERTY_TYPE_LABELS, SOURCE_LABELS } from "@/lib/format";
import {
  type FieldErrors,
  type LeadField,
  LEAD_FIELDS,
  formValues,
  validateLead,
} from "@/lib/validation/lead";

import type { LeadFormState } from "@/lib/lead-form-state";

type Action = (
  state: LeadFormState,
  formData: FormData,
) => Promise<LeadFormState>;

const inputClass = (invalid: boolean) =>
  cx(
    "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-inset focus:ring-2",
    invalid
      ? "ring-red-400 focus:ring-red-600"
      : "ring-slate-300 focus:ring-brand-600",
  );

type FieldProps = {
  name: LeadField;
  label: string;
  required?: boolean;
  type?: string;
  autoComplete?: string;
  hint?: string;
  error?: string;
  defaultValue?: string;
};

function TextField({
  name,
  label,
  required,
  type = "text",
  autoComplete,
  hint,
  error,
  defaultValue,
}: FieldProps) {
  const id = `lead-${name}`;
  const describedBy =
    [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ") ||
    undefined;
  return (
    <div>
      <label htmlFor={id} className="text-sm font-medium text-slate-700">
        {label}
        {required ? (
          <span className="text-red-600" aria-hidden="true">
            {" "}
            *
          </span>
        ) : (
          <span className="font-normal text-slate-500"> (optional)</span>
        )}
      </label>
      <input
        id={id}
        name={name}
        type={type}
        autoComplete={autoComplete}
        defaultValue={defaultValue}
        required={required}
        aria-required={required}
        aria-invalid={Boolean(error)}
        aria-describedby={describedBy}
        className={inputClass(Boolean(error))}
      />
      {hint && (
        <p id={`${id}-hint`} className="mt-1 text-xs text-slate-500">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="mt-1 text-sm text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}

const LABELS: Record<LeadField, string> = {
  first_name: "First name",
  last_name: "Last name",
  company_name: "Company",
  email: "E-mail",
  phone: "Phone",
  job_title: "Job title",
  source: "Source",
  property_type: "Property type",
  budget_min_inr: "Minimum budget",
  budget_max_inr: "Maximum budget",
  location: "Location",
};

/**
 * Lead form used by "New lead" and "Edit lead". Validates in the browser first; the
 * server action validates again, and the API validates a third time.
 */
export function LeadForm({
  action,
  initialState,
  submitLabel = "Create lead",
  pendingLabel = "Creating…",
  errorTitle = "The lead could not be created",
  cancelHref = "/leads",
  hidden = {},
}: {
  action: Action;
  initialState: LeadFormState;
  submitLabel?: string;
  pendingLabel?: string;
  errorTitle?: string;
  cancelHref?: string;
  /** Extra values sent with the form, e.g. the optimistic-lock version. */
  hidden?: Record<string, string>;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const [clientErrors, setClientErrors] = useState<FieldErrors | null>(null);
  const formRef = useRef<HTMLFormElement>(null);

  const errors: FieldErrors = clientErrors ?? state.fieldErrors;
  const errorCount = Object.keys(errors).length;
  const values = state.values;

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    const result = validateLead(formValues(new FormData(event.currentTarget)));
    if (!result.ok) {
      event.preventDefault();
      setClientErrors(result.errors);
      // Move keyboard focus to the first field that needs fixing.
      const first = LEAD_FIELDS.find((f) => result.errors[f]);
      if (first)
        formRef.current
          ?.querySelector<HTMLElement>(`[name="${first}"]`)
          ?.focus();
      return;
    }
    setClientErrors(null);
  }

  return (
    // key: re-mount with the submitted values after a server-side error.
    <form
      key={state.attempt}
      ref={formRef}
      action={formAction}
      onSubmit={onSubmit}
      noValidate
      className="space-y-6"
    >
      {state.error && !clientErrors && (
        <ErrorAlert title={errorTitle} error={state.error} />
      )}
      {Object.entries(hidden).map(([name, value]) => (
        <input key={name} type="hidden" name={name} value={value} />
      ))}
      {errorCount > 0 && (
        <div
          role="alert"
          className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
        >
          Please correct {errorCount === 1 ? "1 field" : `${errorCount} fields`}{" "}
          below.
        </div>
      )}

      <fieldset className="grid gap-5 sm:grid-cols-2">
        <legend className="sr-only">Person</legend>
        <TextField
          name="first_name"
          label={LABELS.first_name}
          autoComplete="off"
          error={errors.first_name}
          defaultValue={values.first_name}
        />
        <TextField
          name="last_name"
          label={LABELS.last_name}
          required
          autoComplete="off"
          error={errors.last_name}
          defaultValue={values.last_name}
        />
        <TextField
          name="email"
          label={LABELS.email}
          type="email"
          autoComplete="off"
          error={errors.email}
          defaultValue={values.email}
        />
        <TextField
          name="phone"
          label={LABELS.phone}
          type="tel"
          autoComplete="off"
          hint="Digits, spaces and + ( ) . - only"
          error={errors.phone}
          defaultValue={values.phone}
        />
      </fieldset>

      <fieldset className="grid gap-5 sm:grid-cols-2">
        <legend className="sr-only">Company</legend>
        <TextField
          name="company_name"
          label={LABELS.company_name}
          autoComplete="off"
          error={errors.company_name}
          defaultValue={values.company_name}
        />
        <TextField
          name="job_title"
          label={LABELS.job_title}
          autoComplete="off"
          error={errors.job_title}
          defaultValue={values.job_title}
        />
        <div>
          <label
            htmlFor="lead-source"
            className="text-sm font-medium text-slate-700"
          >
            {LABELS.source}{" "}
            <span className="font-normal text-slate-500">(optional)</span>
          </label>
          <select
            id="lead-source"
            name="source"
            defaultValue={values.source ?? ""}
            aria-invalid={Boolean(errors.source)}
            aria-describedby={errors.source ? "lead-source-error" : undefined}
            className={inputClass(Boolean(errors.source))}
          >
            <option value="">Not specified</option>
            {LEAD_SOURCES.map((s) => (
              <option key={s} value={s}>
                {SOURCE_LABELS[s]}
              </option>
            ))}
          </select>
          {errors.source && (
            <p id="lead-source-error" className="mt-1 text-sm text-red-700">
              {errors.source}
            </p>
          )}
        </div>
      </fieldset>

      <fieldset className="grid gap-5 sm:grid-cols-2">
        <legend className="mb-3 text-sm font-semibold text-slate-900">
          Property wishes
        </legend>
        <div>
          <label
            htmlFor="lead-property_type"
            className="text-sm font-medium text-slate-700"
          >
            {LABELS.property_type}{" "}
            <span className="font-normal text-slate-500">(optional)</span>
          </label>
          <select
            id="lead-property_type"
            name="property_type"
            defaultValue={values.property_type ?? ""}
            aria-invalid={Boolean(errors.property_type)}
            aria-describedby={
              errors.property_type ? "lead-property_type-error" : undefined
            }
            className={inputClass(Boolean(errors.property_type))}
          >
            <option value="">Not specified</option>
            {PROPERTY_TYPES.map((t) => (
              <option key={t} value={t}>
                {PROPERTY_TYPE_LABELS[t]}
              </option>
            ))}
          </select>
          {errors.property_type && (
            <p id="lead-property_type-error" className="mt-1 text-sm text-red-700">
              {errors.property_type}
            </p>
          )}
        </div>
        <TextField
          name="location"
          label={LABELS.location}
          autoComplete="off"
          hint="Area or city, e.g. Kokapet, Hyderabad"
          error={errors.location}
          defaultValue={values.location}
        />
        <TextField
          name="budget_min_inr"
          label={LABELS.budget_min_inr}
          autoComplete="off"
          hint="Whole rupees, or 1.2 Cr / 80 L"
          error={errors.budget_min_inr}
          defaultValue={values.budget_min_inr}
        />
        <TextField
          name="budget_max_inr"
          label={LABELS.budget_max_inr}
          autoComplete="off"
          hint="Whole rupees, or 1.5 Cr / 95 L"
          error={errors.budget_max_inr}
          defaultValue={values.budget_max_inr}
        />
      </fieldset>

      <div className="flex items-center justify-end gap-3 border-t border-slate-200 pt-5">
        <Link href={cancelHref} className={buttonClass("secondary")}>
          Cancel
        </Link>
        <button
          type="submit"
          disabled={pending}
          aria-disabled={pending}
          className={buttonClass("primary")}
        >
          {pending ? pendingLabel : submitLabel}
        </button>
      </div>
    </form>
  );
}

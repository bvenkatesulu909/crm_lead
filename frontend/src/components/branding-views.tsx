"use client";

import { useActionState, useState } from "react";

import { DialogField } from "@/components/action-dialog";
import { ErrorAlert, buttonClass } from "@/components/ui";
import {
  FIELD_LABELS,
  TEXT_LIMITS,
  normalizeColor,
  readableTextColor,
  type Branding,
  type TextField,
} from "@/lib/branding";
import type { FormState } from "@/lib/form-state";
import { initialFormState } from "@/lib/form-state";

type FormAction = (state: FormState, formData: FormData) => Promise<FormState>;
type PlainAction = (state: FormState) => Promise<FormState>;

/** A small picture of the cover slide, so the colour and logo can be judged before a deck is made. */
export function CoverPreview({
  color,
  logoSrc,
  name,
}: {
  color: string;
  logoSrc: string | null;
  name: string;
}) {
  const hex = normalizeColor(color) ?? "1f3a5f";
  return (
    <div
      data-testid="cover-preview"
      className="flex aspect-video w-full max-w-md flex-col justify-between rounded-md p-5"
      style={{ backgroundColor: `#${hex}`, color: readableTextColor(hex) }}
    >
      {logoSrc ? (
        // eslint-disable-next-line @next/next/no-img-element -- a small stored PNG, shown as is
        <img
          src={logoSrc}
          alt="Your logo"
          className="max-h-14 w-auto self-start"
        />
      ) : (
        <span className="text-xs opacity-70">No logo yet</span>
      )}
      <div>
        <p className="text-lg font-semibold">Proposal for your customer</p>
        <p className="text-xs opacity-80">{name}</p>
      </div>
    </div>
  );
}

/** The colour and the four texts. Texts are plain text; the server takes out links and markup. */
export function BrandingForm({
  action,
  branding,
  organisation,
  logoSrc,
}: {
  action: FormAction;
  branding: Branding;
  organisation: string;
  logoSrc: string | null;
}) {
  const [state, formAction, pending] = useActionState(action, initialFormState);
  const initial = (name: string, fallback: string) =>
    state.values[name] ?? fallback;
  const [color, setColor] = useState(branding.primary_color);
  const shown = normalizeColor(color) ?? branding.primary_color;
  return (
    <form
      key={state.attempt}
      action={formAction}
      noValidate
      className="space-y-5"
    >
      {state.error && (
        <ErrorAlert
          title="The branding could not be saved"
          error={state.error}
        />
      )}
      <div className="flex flex-wrap items-end gap-4">
        <div className="w-44">
          <DialogField
            id="brand-color"
            label="Brand colour"
            error={state.fieldErrors.primary_color}
            hint="Six hex digits, e.g. 1F3A5F."
          >
            {(p) => (
              <input
                name="primary_color"
                value={color}
                onChange={(e) => setColor(e.target.value)}
                maxLength={7}
                autoComplete="off"
                {...p}
              />
            )}
          </DialogField>
        </div>
        <CoverPreview color={shown} logoSrc={logoSrc} name={organisation} />
      </div>
      {(Object.keys(TEXT_LIMITS) as TextField[]).map((field) => {
        const long = field === "about_text" || field === "terms_text";
        return (
          <DialogField
            key={field}
            id={`brand-${field}`}
            label={FIELD_LABELS[field]}
            optional
            error={state.fieldErrors[field]}
            hint={`Plain text, at most ${TEXT_LIMITS[field]} characters. Links are removed.`}
          >
            {(p) =>
              long ? (
                <textarea
                  name={field}
                  rows={5}
                  maxLength={TEXT_LIMITS[field] * 2}
                  defaultValue={initial(field, branding[field])}
                  {...p}
                />
              ) : (
                <input
                  name={field}
                  maxLength={TEXT_LIMITS[field] * 2}
                  defaultValue={initial(field, branding[field])}
                  {...p}
                />
              )
            }
          </DialogField>
        );
      })}
      <button
        type="submit"
        disabled={pending}
        className={buttonClass("primary")}
      >
        {pending ? "Saving…" : "Save branding"}
      </button>
    </form>
  );
}

/** Upload or remove the logo. Only a PNG or JPEG of at most 1 MB is sent; the server draws it again. */
export function LogoPanel({
  upload,
  remove,
  hasLogo,
}: {
  upload: FormAction;
  remove: PlainAction;
  hasLogo: boolean;
}) {
  const [state, formAction, pending] = useActionState(upload, initialFormState);
  const [removed, removeAction, removing] = useActionState(
    remove,
    initialFormState,
  );
  const error = state.error ?? removed.error;
  return (
    <div className="space-y-3">
      {error && (
        <ErrorAlert title="The logo could not be changed" error={error} />
      )}
      <form key={state.attempt} action={formAction} className="space-y-2">
        <DialogField
          id="brand-logo"
          label={hasLogo ? "Replace the logo" : "Logo"}
          error={state.fieldErrors.file}
          hint="PNG or JPEG, at most 1 MB. It is stored as a small clean PNG."
        >
          {(p) => (
            <input
              type="file"
              name="file"
              accept="image/png,image/jpeg"
              {...p}
            />
          )}
        </DialogField>
        <button
          type="submit"
          disabled={pending}
          className={buttonClass("secondary")}
        >
          {pending ? "Uploading…" : hasLogo ? "Replace logo" : "Upload logo"}
        </button>
      </form>
      {hasLogo && (
        <form action={removeAction}>
          <button
            type="submit"
            disabled={removing}
            className={buttonClass("secondary")}
          >
            {removing ? "Removing…" : "Remove logo"}
          </button>
        </form>
      )}
    </div>
  );
}

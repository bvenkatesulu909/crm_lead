"use client";

import { useActionState, useState } from "react";

import { DialogField } from "@/components/action-dialog";
import { ErrorAlert, buttonClass, cx } from "@/components/ui";
import type { FormState } from "@/lib/form-state";
import { initialFormState } from "@/lib/form-state";

const WORDS = ["", "Very unhappy", "Unhappy", "Okay", "Happy", "Very happy"];

/** "How did we do?" - 1 to 5 stars and an optional comment, once per resolved ticket. */
export function RatingForm({
  action,
}: {
  action: (state: FormState, formData: FormData) => Promise<FormState>;
}) {
  const [state, formAction, pending] = useActionState(action, initialFormState);
  const [rating, setRating] = useState(Number(state.values.rating ?? 0));

  return (
    <form key={state.attempt} action={formAction} noValidate className="space-y-4 border-t border-slate-200 px-5 py-4">
      {state.error && <ErrorAlert title="Your rating could not be saved" error={state.error} />}
      <fieldset>
        <legend className="text-sm font-medium text-slate-900">How did we do?</legend>
        <div className="mt-2 flex gap-1" role="radiogroup">
          {[1, 2, 3, 4, 5].map((n) => (
            <label key={n} className="cursor-pointer rounded px-0.5 focus-within:ring-2 focus-within:ring-brand-600" title={WORDS[n]}>
              <input type="radio" name="rating" value={n} checked={rating === n} onChange={() => setRating(n)} className="sr-only" />
              <span aria-hidden="true" className={cx("text-3xl", n <= rating ? "text-amber-500" : "text-slate-300")}>★</span>
              <span className="sr-only">{n} – {WORDS[n]}</span>
            </label>
          ))}
          {rating > 0 && <span className="ml-2 self-center text-sm text-slate-600">{WORDS[rating]}</span>}
        </div>
        {state.fieldErrors.rating && <p className="mt-1 text-sm text-red-700">{state.fieldErrors.rating}</p>}
      </fieldset>
      <DialogField id="rating-comment" label="Anything you'd like to add?" optional error={state.fieldErrors.comment}>
        {(p) => <textarea name="comment" rows={2} maxLength={1000} defaultValue={state.values.comment} {...p} />}
      </DialogField>
      <button type="submit" disabled={pending} className={buttonClass("primary")}>
        {pending ? "Sending…" : "Send rating"}
      </button>
    </form>
  ); // prettier-ignore
}

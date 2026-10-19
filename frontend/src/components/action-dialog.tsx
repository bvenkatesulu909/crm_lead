"use client";

import {
  useActionState,
  useEffect,
  useId,
  useRef,
  type ReactNode,
} from "react";

import { ErrorAlert, buttonClass, cx } from "@/components/ui";
import type { DialogState } from "@/lib/dialog-state";

type Variant = "primary" | "secondary" | "danger";

/**
 * A button that opens a confirmation dialog with a form. Used for every action that changes a
 * lead, so nothing happens on a single accidental click:
 *   1. click the button -> dialog explains what will happen (and may ask for input)
 *   2. click the confirm button -> the Server Action runs
 * Built on the native <dialog> element: focus is kept inside, Escape cancels, and focus
 * returns to the button afterwards.
 */
export function ActionDialog({
  triggerLabel,
  triggerVariant = "secondary",
  title,
  description,
  confirmLabel,
  confirmVariant = "primary",
  action,
  initialState,
  children,
}: {
  triggerLabel: string;
  triggerVariant?: Variant;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  confirmVariant?: Variant;
  action: (state: DialogState, formData: FormData) => Promise<DialogState>;
  initialState: DialogState;
  /** Form fields; receive the current field errors to display. */
  children?: (errors: Record<string, string>) => ReactNode;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  // Keep the dialog open to show errors returned by the server.
  useEffect(() => {
    if (state.attempt > 0 && dialog.current && !dialog.current.open)
      dialog.current.showModal();
  }, [state.attempt]);

  return (
    <>
      <button
        type="button"
        className={buttonClass(triggerVariant)}
        onClick={() => dialog.current?.showModal()}
      >
        {triggerLabel}
      </button>
      <dialog
        ref={dialog}
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        className="m-auto w-[calc(100%-2rem)] max-w-lg rounded-xl p-0 shadow-xl backdrop:bg-slate-900/50"
      >
        {/* key: after each attempt a fresh form is built from the current props/state. React
            resets forms after an action, and a reset would otherwise put fields back to their
            FIRST values while the rest of the dialog shows newer choices. */}
        <form
          key={state.attempt}
          action={formAction}
          noValidate
          className="space-y-5 p-6"
        >
          <div>
            <h2 id={titleId} className="text-lg font-semibold text-slate-900">
              {title}
            </h2>
            <div id={descriptionId} className="mt-2 text-sm text-slate-600">
              {description}
            </div>
          </div>
          {state.error && (
            <ErrorAlert title="This didn't work" error={state.error} />
          )}
          {children?.(state.fieldErrors)}
          <div className="flex justify-end gap-3 border-t border-slate-200 pt-4">
            <button
              type="button"
              className={buttonClass("secondary")}
              onClick={() => dialog.current?.close()}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={pending}
              className={cx(
                buttonClass(confirmVariant),
                pending && "opacity-70",
              )}
            >
              {pending ? "Working…" : confirmLabel}
            </button>
          </div>
        </form>
      </dialog>
    </>
  );
}

/** Accessible label + control + error message, for dialog forms. */
export function DialogField({
  id,
  label,
  error,
  hint,
  optional,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  hint?: string;
  optional?: boolean;
  children: (props: {
    id: string;
    "aria-invalid": boolean;
    "aria-describedby": string | undefined;
    className: string;
  }) => ReactNode;
}) {
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`]
    .filter(Boolean)
    .join(" ");
  return (
    <div>
      <label htmlFor={id} className="text-sm font-medium text-slate-700">
        {label}
        {optional && (
          <span className="font-normal text-slate-500"> (optional)</span>
        )}
      </label>
      {children({
        id,
        "aria-invalid": Boolean(error),
        "aria-describedby": describedBy || undefined,
        className: cx(
          "mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-inset focus:ring-2",
          error
            ? "ring-red-400 focus:ring-red-600"
            : "ring-slate-300 focus:ring-brand-600",
        ),
      })}
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

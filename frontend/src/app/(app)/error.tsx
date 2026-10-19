"use client";

import { buttonClass } from "@/components/ui";

/** Unexpected error while rendering a page. Details stay in the server log; the user gets a way out. */
export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div
      role="alert"
      className="rounded-lg bg-white p-6 shadow-sm ring-1 ring-slate-200"
    >
      <h1 className="text-lg font-semibold text-slate-900">
        This page could not be displayed
      </h1>
      <p className="mt-2 text-sm text-slate-600">
        Something went wrong while loading it. You can try again; if it keeps
        happening, contact support.
      </p>
      {error.digest && (
        <p className="mt-2 text-xs text-slate-500">
          Reference: <span className="font-mono">{error.digest}</span>
        </p>
      )}
      <button
        type="button"
        onClick={reset}
        className={`${buttonClass("primary")} mt-4`}
      >
        Try again
      </button>
    </div>
  );
}

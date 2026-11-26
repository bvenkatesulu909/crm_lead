"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { deleteEnhancement } from "@/app/(app)/photos/actions";
import { ActionDialog } from "@/components/action-dialog";
import { buttonClass } from "@/components/ui";
import { initialDialogState } from "@/lib/dialog-state";
import { formatBytes, formatDateTime } from "@/lib/format";
import {
  PEOPLE_WARNING,
  PHOTO_REFRESH_MS,
  copyStateText,
  isWorking,
  type Enhancement,
} from "@/lib/photo-enhancer";

/**
 * The adjusted copies of one photo (ADR 0039): each with an "Enhanced" badge, the list of what was
 * done, the size, a download and "Show original" side by side. While a copy is being made the page
 * looks again every few seconds. Copies are plain pictures from this app's own download route.
 */
export function PhotoCopies({
  documentId,
  copies,
  caption,
  canDelete,
  refreshMs = PHOTO_REFRESH_MS,
}: {
  documentId: string;
  copies: Enhancement[];
  caption: string;
  canDelete: boolean;
  refreshMs?: number;
}) {
  const router = useRouter();
  const working = isWorking(copies);
  useEffect(() => {
    if (!working) return;
    const timer = setInterval(() => router.refresh(), refreshMs);
    return () => clearInterval(timer);
  }, [working, router, refreshMs]);

  if (copies.length === 0)
    return (
      <p className="text-sm text-slate-600">
        No adjusted copies yet. Set the adjustments above and press “Make
        enhanced copy”.
      </p>
    );
  return (
    <ul className="space-y-4" data-testid="photo-copies">
      {copies.map((copy) => (
        <li
          key={copy.id}
          className="rounded-md border border-slate-200 p-4"
          data-status={copy.status}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              {copy.status === "ready" && (
                <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-800">
                  Enhanced
                </span>
              )}
              <p
                className="text-sm text-slate-800"
                role={copy.status === "queued" ? "status" : undefined}
              >
                {copyStateText(copy)}
              </p>
            </div>
            <p className="text-xs text-slate-500">
              {formatDateTime(copy.created_at)}
              {copy.size_bytes !== null && ` · ${formatBytes(copy.size_bytes)}`}
              {copy.width !== null &&
                copy.height !== null &&
                ` · ${copy.width} × ${copy.height} px`}
            </p>
          </div>
          {copy.applied && copy.applied.length > 0 && (
            <ul className="mt-2 list-disc pl-5 text-sm text-slate-700">
              {copy.applied.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ul>
          )}
          {copy.status === "ready" && (
            <>
              <details className="mt-3">
                <summary className="cursor-pointer text-sm text-brand-700">
                  Show original
                </summary>
                <div className="mt-2 grid gap-3 sm:grid-cols-2">
                  <figure>
                    {/* eslint-disable-next-line @next/next/no-img-element -- a download route */}
                    <img
                      src={`/documents/${documentId}/download`}
                      alt="Original photo"
                      className="max-h-72 max-w-full"
                    />
                    <figcaption className="text-xs text-slate-500">
                      Original (kept as it was)
                    </figcaption>
                  </figure>
                  <figure>
                    {/* eslint-disable-next-line @next/next/no-img-element -- a download route */}
                    <img
                      src={`/photos/copies/${copy.id}/download`}
                      alt="Enhanced copy"
                      className="max-h-72 max-w-full"
                    />
                    <figcaption className="text-xs text-slate-500">
                      Enhanced copy
                    </figcaption>
                  </figure>
                </div>
              </details>
              <p className="mt-2 text-xs text-slate-500">
                In decks and brochures this copy carries the line “{caption}”.{" "}
                {PEOPLE_WARNING}
              </p>
            </>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            {copy.status === "ready" && (
              <a
                href={`/photos/copies/${copy.id}/download`}
                download
                className={buttonClass("secondary")}
              >
                Download copy
              </a>
            )}
            {canDelete && (
              <ActionDialog
                triggerLabel="Delete copy"
                triggerVariant="secondary"
                title="Delete this adjusted copy?"
                description="Your original photo is not touched. This cannot be undone."
                confirmLabel="Delete"
                confirmVariant="danger"
                action={deleteEnhancement.bind(null, documentId, copy.id)}
                initialState={initialDialogState}
              />
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

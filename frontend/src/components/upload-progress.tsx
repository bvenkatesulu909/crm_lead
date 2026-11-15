"use client";

/** Shown while a file goes from the browser to the file store (ADR 0025). */
export function UploadProgress({ percent }: { percent: number | null }) {
  if (percent === null) return null;
  return (
    // aria-live, not role="status": the page's own "uploaded" notice is the status region.
    <div aria-live="polite" className="space-y-1">
      <progress
        value={percent}
        max={100}
        aria-label="Upload progress"
        className="h-2 w-full overflow-hidden rounded-full accent-brand-600"
      />
      <p className="text-xs text-slate-600">
        {percent < 100
          ? `Sending the file… ${percent} %`
          : "Checking the file…"}
      </p>
    </div>
  );
}

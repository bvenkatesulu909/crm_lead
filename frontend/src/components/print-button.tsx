"use client";

import { buttonClass } from "@/components/ui";

/** Opens the browser's print dialog (choose "Save as PDF" to get a PDF). */
export function PrintButton() {
  return (
    <button
      type="button"
      onClick={() => window.print()}
      className={buttonClass("primary")}
    >
      Print / Save as PDF
    </button>
  );
}

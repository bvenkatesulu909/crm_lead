import Link from "next/link";

import { cx } from "@/components/ui";

/**
 * "Showing 21–40 of 57" with Previous / Next links. Pure and link-based: works without
 * JavaScript and keeps the page in the URL (shareable, back button works).
 */
export function Pagination({
  total,
  page,
  pageSize,
  hrefForPage,
}: {
  total: number;
  page: number;
  pageSize: number;
  hrefForPage: (page: number) => string;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const last = Math.min(total, page * pageSize);
  const linkClass =
    "rounded-md px-3 py-1.5 text-sm font-medium ring-1 ring-inset ring-slate-300 bg-white text-slate-700 hover:bg-slate-50";
  const disabledClass =
    "rounded-md px-3 py-1.5 text-sm font-medium text-slate-400 ring-1 ring-inset ring-slate-200";

  return (
    <nav
      aria-label="Pagination"
      className="flex items-center justify-between gap-4 px-5 py-3"
    >
      <p className="text-sm text-slate-600" aria-live="polite">
        {total === 0 ? "No results" : `Showing ${first}–${last} of ${total}`}
      </p>
      <div className="flex items-center gap-2">
        {page > 1 ? (
          <Link href={hrefForPage(page - 1)} className={linkClass} rel="prev">
            Previous
          </Link>
        ) : (
          <span aria-disabled="true" className={disabledClass}>
            Previous
          </span>
        )}
        <span className="text-sm text-slate-600">
          Page <span aria-current="page">{Math.min(page, pages)}</span> of{" "}
          {pages}
        </span>
        {page < pages ? (
          <Link
            href={hrefForPage(page + 1)}
            className={cx(linkClass)}
            rel="next"
          >
            Next
          </Link>
        ) : (
          <span aria-disabled="true" className={disabledClass}>
            Next
          </span>
        )}
      </div>
    </nav>
  );
}

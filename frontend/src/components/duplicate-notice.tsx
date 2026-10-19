import Link from "next/link";

import type { DuplicateNotice as Notice } from "@/lib/form-state";

/**
 * Shown above a create form when the new record looks like existing ones. The user either
 * opens the existing record or ticks the box to create the new one anyway.
 */
export function DuplicateNotice({
  notice,
  what,
}: {
  notice: Notice;
  what: "customer" | "contact";
}) {
  const total = notice.items.length + notice.hidden;
  return (
    <div
      role="alert"
      className="space-y-3 rounded-md border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900"
    >
      <p className="font-semibold">
        This may be an existing {what} ({total} possible match
        {total === 1 ? "" : "es"}).
      </p>
      {notice.items.length > 0 && (
        <ul className="list-inside list-disc space-y-1">
          {notice.items.map((item) => (
            <li key={item.href}>
              <Link
                href={item.href}
                className="font-medium text-brand-700 hover:underline"
              >
                {item.label}
              </Link>{" "}
              <span className="text-amber-800">— {item.detail}</span>
            </li>
          ))}
        </ul>
      )}
      {notice.hidden > 0 && (
        <p>
          {notice.hidden} matching {what}
          {notice.hidden === 1 ? " belongs" : "s belong"} to a colleague. Ask
          your manager before creating a second record.
        </p>
      )}
      <label className="flex items-start gap-2">
        <input type="checkbox" name="confirm_new" className="mt-0.5" />
        <span>This is a different {what} — create it anyway.</span>
      </label>
    </div>
  );
}

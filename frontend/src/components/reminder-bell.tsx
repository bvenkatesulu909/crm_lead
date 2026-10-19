import Link from "next/link";

/**
 * Header bell: how many of the user's own open items need attention (overdue, due within
 * 24 hours or reminder time passed). Server-rendered on every page load; no polling.
 */
export function ReminderBell({ count }: { count: number }) {
  const label =
    count === 0
      ? "Tasks: nothing urgent"
      : `Tasks: ${count} need${count === 1 ? "s" : ""} attention`;
  return (
    <Link
      href="/tasks"
      aria-label={label}
      title={label}
      className="relative rounded-full p-2 text-slate-600 hover:bg-slate-100 hover:text-slate-900"
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
        <path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0" />
      </svg>
      {count > 0 && (
        <span className="absolute -right-0.5 -top-0.5 flex min-w-5 items-center justify-center rounded-full bg-red-600 px-1 text-xs font-semibold text-white">
          {count > 99 ? "99+" : count}
        </span>
      )}
    </Link>
  ); // prettier-ignore
}

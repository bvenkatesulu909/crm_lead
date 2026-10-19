import Link from "next/link";

/** Header inbox: unread notifications (ADR 0006). Server-rendered on each page; no polling. */
export function NotificationBell({ unread }: { unread: number }) {
  const label =
    unread === 0
      ? "Notifications: none unread"
      : `Notifications: ${unread} unread`;
  return (
    <Link
      href="/notifications"
      aria-label={label}
      title={label}
      className="relative rounded-full p-2 text-slate-600 hover:bg-slate-100 hover:text-slate-900"
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 13h5l2 3h4l2-3h5M5 5h14l2 8v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-6z" />
      </svg>
      {unread > 0 && (
        <span className="absolute -right-0.5 -top-0.5 flex min-w-5 items-center justify-center rounded-full bg-brand-600 px-1 text-xs font-semibold text-white">
          {unread > 99 ? "99+" : unread}
        </span>
      )}
    </Link>
  ); // prettier-ignore
}

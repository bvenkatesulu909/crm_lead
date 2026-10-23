"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { cx } from "@/components/ui";
import { MODULE_ICON_PATHS } from "@/lib/module-icons";
import type { ModuleView } from "@/lib/modules";
import type { NavItem } from "@/lib/permissions";

const icons: Record<NavItem["icon"], ReactNode> = {
  home: (
    <path d="M3 10.5 12 3l9 7.5V21a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z" />
  ),
  leads: (
    <path d="M16 11a4 4 0 1 0-8 0M4 21a8 8 0 0 1 16 0M12 7V3m-4 4L6 5m10 2 2-2" />
  ),
  accounts: (
    <path d="M3 21V7l9-4 9 4v14M9 21v-6h6v6M8 10h.01M12 10h.01M16 10h.01" />
  ),
  contacts: (
    <path d="M4 4h13a1 1 0 0 1 1 1v15a1 1 0 0 1-1 1H4zM8 2v4M18 8h2M18 12h2M18 16h2M11 13a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5M7 18a4 4 0 0 1 8 0" />
  ),
  pipeline: <path d="M3 4h4v16H3zM10 4h4v11h-4zM17 4h4v7h-4z" />,
  quotes: (
    <path d="M6 2h9l5 5v15H6zM14 2v6h6M9 12h3M9 16h7M15 11.5a1.5 1.5 0 1 0 0 .01" />
  ),
  contracts: (
    <path d="M6 2h9l5 5v15H6zM14 2v6h6M9 12h5M9 16h3M14 17l1.5 1.5L19 15" />
  ),
  products: <path d="M20 7 12 3 4 7v10l8 4 8-4zM4 7l8 4 8-4M12 11v10" />,
  tasks: (
    <path d="M9 6h11M9 12h11M9 18h11M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2" />
  ),
  orders: <path d="M21 8 12 3 3 8v8l9 5 9-5zM3 8l9 5 9-5M12 13v8" />,
  invoices: <path d="M6 2h9l5 5v15H6zM14 2v6h6M9 13h8M9 17h5" />,
  users: (
    <path d="M16 19a4 4 0 0 0-8 0M12 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6M20 19a3 3 0 0 0-3-3M17 9a2.5 2.5 0 1 0 0-5M4 19a3 3 0 0 1 3-3M7 9a2.5 2.5 0 1 1 0-5" />
  ),
  automation: <path d="M13 2 4 14h7l-1 8 9-12h-7z" />,
  reports: <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />,
  organisations: (
    <path d="M3 21h18M5 21V5l7-3 7 3v16M9 9h1M14 9h1M9 13h1M14 13h1M10 21v-4h4v4" />
  ),
  knowledge: (
    <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2zM8 7h8M8 11h6" />
  ),
  support: (
    <path d="M4 13a8 8 0 1 1 16 0v4a2 2 0 0 1-2 2h-2v-6h4M4 13v4a2 2 0 0 0 2 2h2v-6H4" />
  ),
  assistant: (
    <path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8zM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z" />
  ),
};

function NavIcon({ name }: { name: NavItem["icon"] }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="size-5 shrink-0"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {icons[name]}
    </svg>
  );
}

export function isActive(pathname: string, href: string) {
  return href === "/"
    ? pathname === "/"
    : pathname === href || pathname.startsWith(`${href}/`);
}

export function NavLinks({
  items,
  onNavigate,
}: {
  items: NavItem[];
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  return (
    <ul className="space-y-1">
      {items.map((item) => {
        const active = isActive(pathname, item.href);
        return (
          <li key={item.href}>
            <Link
              href={item.href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={cx(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium",
                active
                  ? "bg-brand-700 text-white"
                  : "text-brand-100 hover:bg-brand-700/60 hover:text-white",
              )}
            >
              <NavIcon name={item.icon} />
              {item.label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

const MODULE_BADGE: Record<ModuleView["status"], string> = {
  available: "",
  in_progress: "Soon",
  planned: "Planned",
};

/**
 * Every CRM module that isn't already in the menu above, so the whole CRM is visible from the
 * sidebar. Only modules that work for this user are links; the rest show why not.
 */
export function ModuleLinks({
  modules,
  onNavigate,
}: {
  modules: ModuleView[];
  onNavigate?: () => void;
}) {
  if (modules.length === 0) return null;
  return (
    <ul className="space-y-0.5">
      {modules.map((m) => {
        const badge = m.link ? "" : MODULE_BADGE[m.status] || "No access";
        const content = (
          <>
            <svg aria-hidden="true" viewBox="0 0 24 24" className="size-4 shrink-0" fill="none"
              stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
              <path d={MODULE_ICON_PATHS[m.key]} />
            </svg>
            <span className="flex-1 leading-tight">{m.name}</span>
            {badge && <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide">{badge}</span>}
          </>
        );
        return (
          <li key={m.key}>
            {m.link ? (
              <Link href={m.link} onClick={onNavigate}
                className="flex items-center gap-2.5 rounded-md px-3 py-1.5 text-sm text-brand-100 hover:bg-brand-700/60 hover:text-white">
                {content}
              </Link>
            ) : (
              <div title={`${m.name}: ${m.note}`} aria-label={`${m.name}: ${m.note}`}
                className="flex cursor-default items-center gap-2.5 rounded-md px-3 py-1.5 text-sm text-brand-100/60">
                {content}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  ); // prettier-ignore
}

function SidebarModules({
  modules,
  onNavigate,
}: {
  modules: ModuleView[];
  onNavigate?: () => void;
}) {
  if (modules.length === 0) return null;
  return (
    <nav
      aria-label="All CRM modules"
      className="border-t border-white/10 px-3 pt-4"
    >
      <ModuleLinks modules={modules} onNavigate={onNavigate} />
    </nav>
  );
}

function Brand() {
  return (
    <Link
      href="/"
      className="flex items-center gap-2 px-3 text-lg font-semibold text-white"
    >
      <span
        aria-hidden="true"
        className="grid size-8 place-items-center rounded-md bg-white/15"
      >
        CL
      </span>
      crm-lead
    </Link>
  );
}

/**
 * Page frame: sidebar (desktop) / slide-in menu (mobile), top bar and main area.
 * Navigation entries come from the server, already filtered by the user's permissions.
 */
export function AppShell({
  nav,
  modules = [],
  userMenu,
  headerActions,
  children,
}: {
  nav: NavItem[];
  /** CRM modules not already in `nav` (shown below it). */
  modules?: ModuleView[];
  userMenu: ReactNode;
  /** Shown before the user menu, e.g. the reminders bell. */
  headerActions?: ReactNode;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const drawerId = useId();
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    closeButton.current?.focus();
    const onKey = (event: KeyboardEvent) =>
      event.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="min-h-screen">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-white focus:px-4 focus:py-2 focus:shadow"
      >
        Skip to main content
      </a>

      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-64 flex-col gap-6 overflow-y-auto bg-brand-800 py-5 lg:flex">
        <Brand />
        <nav aria-label="Main" className="px-3">
          <NavLinks items={nav} />
        </nav>
        <SidebarModules modules={modules} />
      </aside>

      {/* Mobile slide-in menu */}
      {open && (
        <div
          className="fixed inset-0 z-40 lg:hidden"
          role="dialog"
          aria-modal="true"
          aria-label="Main menu"
          id={drawerId}
        >
          <div
            className="absolute inset-0 bg-slate-900/50"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <div className="relative flex h-full w-72 max-w-[80%] flex-col gap-6 overflow-y-auto bg-brand-800 py-5">
            <div className="flex items-center justify-between pr-3">
              <Brand />
              <button
                ref={closeButton}
                type="button"
                onClick={() => setOpen(false)}
                className="rounded-md p-2 text-brand-100 hover:bg-brand-700"
              >
                <span className="sr-only">Close menu</span>
                <svg
                  aria-hidden="true"
                  viewBox="0 0 24 24"
                  className="size-5"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path d="M6 6l12 12M18 6 6 18" />
                </svg>
              </button>
            </div>
            <nav aria-label="Main" className="px-3">
              <NavLinks items={nav} onNavigate={() => setOpen(false)} />
            </nav>
            <SidebarModules
              modules={modules}
              onNavigate={() => setOpen(false)}
            />
          </div>
        </div>
      )}

      <div className="lg:pl-64">
        <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-slate-200 bg-white/95 px-4 backdrop-blur sm:px-6">
          <button
            type="button"
            onClick={() => setOpen(true)}
            aria-expanded={open}
            aria-controls={drawerId}
            className="rounded-md p-2 text-slate-600 hover:bg-slate-100 lg:hidden"
          >
            <span className="sr-only">Open menu</span>
            <svg
              aria-hidden="true"
              viewBox="0 0 24 24"
              className="size-6"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <div className="flex-1" />
          {headerActions}
          {userMenu}
        </header>
        <main
          id="main"
          tabIndex={-1}
          className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8"
        >
          {children}
        </main>
      </div>
    </div>
  );
}
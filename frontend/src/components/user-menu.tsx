"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";

import { logout } from "@/app/actions/auth";
import { ROLE_LABELS } from "@/lib/permissions";

export function initials(name: string) {
  const parts = name
    .trim()
    .split(/[\s.@_-]+/)
    .filter(Boolean);
  return (
    (parts[0]?.[0] ?? "?").toUpperCase() + (parts[1]?.[0] ?? "").toUpperCase()
  );
}

/** Top-right menu: who is signed in, their roles, and sign out. */
export function UserMenu({
  name,
  email,
  roles,
  profileHref = "/profile",
}: {
  name: string;
  email: string | null;
  roles: string[];
  /** null hides the profile link (e.g. in the customer portal). */
  profileHref?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const container = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        button.current?.focus();
      }
    };
    const onClick = (event: MouseEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  const roleText =
    roles.map((r) => ROLE_LABELS[r] ?? r).join(", ") || "No CRM role";

  return (
    <div className="relative" ref={container}>
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-3 rounded-full py-1 pl-1 pr-3 hover:bg-slate-100"
      >
        <span
          aria-hidden="true"
          className="grid size-8 place-items-center rounded-full bg-brand-600 text-xs font-semibold text-white"
        >
          {initials(name)}
        </span>
        <span className="hidden text-left sm:block">
          <span className="block text-sm font-medium text-slate-900">
            {name}
          </span>
          <span className="block text-xs text-slate-500">{roleText}</span>
        </span>
        <span className="sr-only">Account menu</span>
      </button>
      {open && (
        <div
          id={menuId}
          className="absolute right-0 mt-2 w-64 rounded-md bg-white p-2 shadow-lg ring-1 ring-slate-200"
        >
          <div className="border-b border-slate-100 px-3 pb-3 pt-1">
            <p className="text-sm font-medium text-slate-900">{name}</p>
            {email && (
              <p className="truncate text-xs text-slate-500">{email}</p>
            )}
            <p className="mt-1 text-xs text-slate-500">{roleText}</p>
          </div>
          {profileHref && (
            <Link
              href={profileHref}
              onClick={() => setOpen(false)}
              className="mt-2 block rounded-md px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
            >
              Your profile
            </Link>
          )}
          <form action={logout}>
            <button
              type="submit"
              className="w-full rounded-md px-3 py-2 text-left text-sm font-medium text-slate-700 hover:bg-slate-100"
            >
              Sign out
            </button>
          </form>
        </div>
      )}
    </div>
  );
}

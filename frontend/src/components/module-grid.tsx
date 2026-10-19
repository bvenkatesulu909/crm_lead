import Link from "next/link";

import { cx } from "@/components/ui";
import { MODULE_ICON_PATHS as ICON_PATHS } from "@/lib/module-icons";
import type { ModuleStatus, ModuleView } from "@/lib/modules";

const STATUS: Record<ModuleStatus, { label: string; className: string }> = {
  available: {
    label: "Available",
    className: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  },
  in_progress: {
    label: "In progress",
    className: "bg-amber-50 text-amber-800 ring-amber-200",
  },
  planned: {
    label: "Planned",
    className: "bg-slate-100 text-slate-600 ring-slate-200",
  },
};

function ModuleCard({ module }: { module: ModuleView }) {
  const status = STATUS[module.status];
  const body = (
    <>
      <div className="flex items-start justify-between gap-3">
        <span
          aria-hidden="true"
          className={cx(
            "grid size-10 shrink-0 place-items-center rounded-lg",
            module.link ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-500",
          )}
        >
          <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor"
            strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
            <path d={ICON_PATHS[module.key]} />
          </svg>
        </span>
        <span className={cx("rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset", status.className)}>
          {status.label}
        </span>
      </div>
      <h3 className="mt-4 text-sm font-semibold text-slate-900">{module.name}</h3>
      <p className="mt-1 text-sm text-slate-600">{module.description}</p>
      <p className={cx("mt-3 text-xs font-medium", module.link ? "text-brand-700" : "text-slate-500")}>
        {module.link ? "Open module →" : module.note}
      </p>
    </>
  ); // prettier-ignore

  return (
    <li>
      {module.link ? (
        <Link
          href={module.link}
          className="block h-full rounded-lg bg-white p-5 shadow-sm ring-1 ring-slate-200 transition hover:shadow-md hover:ring-brand-600"
        >
          {body}
        </Link>
      ) : (
        <div
          className="h-full rounded-lg bg-white/70 p-5 ring-1 ring-slate-200"
          aria-label={`${module.name}: ${status.label}. ${module.note}.`}
        >
          {body}
        </div>
      )}
    </li>
  );
}

/** Overview of all CRM modules and how far each one is built. */
export function ModuleGrid({ modules }: { modules: ModuleView[] }) {
  const ready = modules.filter((m) => m.status === "available").length;
  return (
    <section aria-labelledby="modules-heading" className="mt-8">
      <div className="mb-4 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <h2
          id="modules-heading"
          className="text-lg font-semibold text-slate-900"
        >
          CRM modules
        </h2>
        <p className="text-sm text-slate-600">
          {ready} of {modules.length} available · more are added phase by phase
        </p>
      </div>
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {modules.map((module) => (
          <ModuleCard key={module.key} module={module} />
        ))}
      </ul>
    </section>
  );
}

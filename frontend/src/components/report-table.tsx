import type { ReportTable } from "@/lib/api-types";

const RIGHT = new Set(["number", "money", "percent"]);

/** A report section: values come from the API already formatted (names, not IDs). */
export function ReportTableView({ table }: { table: ReportTable }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <caption className="sr-only">{table.title}</caption>
        <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
          <tr>
            {table.columns.map((c) => (
              <th key={c.key} scope="col" className={`px-4 py-2 ${RIGHT.has(c.kind) ? "text-right" : ""}`}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {table.rows.length === 0 ? (
            <tr><td colSpan={table.columns.length} className="px-4 py-6 text-center text-slate-500">No data for this period.</td></tr>
          ) : (
            table.rows.map((row, i) => (
              <tr key={i}>
                {table.columns.map((c) => (
                  <td key={c.key} className={`px-4 py-2 ${RIGHT.has(c.kind) ? "text-right whitespace-nowrap" : ""}`}>{row[c.key] ?? "—"}</td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  ); // prettier-ignore
}

import type { ModuleIcon } from "@/lib/modules";

/** SVG path per CRM module (24x24, stroked) - used by the dashboard grid and the sidebar. */
export const MODULE_ICON_PATHS: Record<ModuleIcon, string> = {
  leads: "M16 11a4 4 0 1 0-8 0M4 21a8 8 0 0 1 16 0M12 7V3",
  customers: "M3 21V7l9-4 9 4v14M9 21v-6h6v6M8 10h.01M12 10h.01M16 10h.01",
  opportunities: "M3 17l6-6 4 4 8-8M15 7h6v6",
  activities:
    "M8 3v3M16 3v3M3 9h18M5 6h14a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2zM8 14l2.5 2.5L16 12",
  catalog: "M21 8l-9-5-9 5 9 5 9-5zM3 8v8l9 5 9-5V8M12 13v8",
  quotes: "M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6",
  contracts: "M7 3h7l5 5v13H7zM14 3v5h5M10 12h6M10 16h3M15 17l1.5 1.5L20 15",
  orders: "M3 4h2l2.5 11h11L21 7H6.5M10 20h.01M17 20h.01",
  invoices: "M6 3h12v18l-3-2-3 2-3-2-3 2zM9 8h6M9 12h6M9 16h3",
  support:
    "M4 13a8 8 0 1 1 16 0v4a2 2 0 0 1-2 2h-2v-6h4M4 13v4a2 2 0 0 0 2 2h2v-6H4",
  marketing:
    "M3 11v2a1 1 0 0 0 1 1h3l6 4V6L7 10H4a1 1 0 0 0-1 1zM17 8a5 5 0 0 1 0 8",
  reports: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  integrations: "M9 7V3M15 7V3M6 7h12v4a6 6 0 0 1-12 0zM12 17v4",
  assistant:
    "M12 3l1.8 4.2L18 9l-4.2 1.8L12 15l-1.8-4.2L6 9l4.2-1.8zM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z",
  contacts:
    "M4 4h13a1 1 0 0 1 1 1v15a1 1 0 0 1-1 1H4zM8 2v4M11 13a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5M7 18a4 4 0 0 1 8 0",
  portal: "M3 5h18v12H3zM8 21h8M12 17v4M7 9h4M7 13h7",
  documents: "M6 2h9l5 5v15H6zM14 2v6h6M9 13h6M9 17h6",
  communication: "M3 5h18v12H8l-5 4zM7 9h10M7 13h6",
  workflows: "M5 3v6M5 15v6M5 9a3 3 0 0 0 3 3h8a3 3 0 0 1 3 3v6M19 3v6",
  knowledge:
    "M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2zM8 7h8M8 11h6",
  approvals: "M9 12l2 2 4-4M12 3l8 3v6c0 4.5-3.2 8.3-8 9-4.8-.7-8-4.5-8-9V6z",
  administration:
    "M12 2l8 4v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6zM9 12l2 2 4-4",
};

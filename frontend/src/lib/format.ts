import type { Lead } from "@/lib/api-types";

const dateFormat = new Intl.DateTimeFormat("en-GB", { dateStyle: "medium" });

export function formatDate(iso: string): string {
  return dateFormat.format(new Date(iso));
}

export function leadName(lead: Pick<Lead, "first_name" | "last_name">): string {
  return [lead.first_name, lead.last_name].filter(Boolean).join(" ");
}

export const SOURCE_LABELS: Record<string, string> = {
  web: "Website",
  referral: "Referral",
  event: "Event",
  cold_call: "Cold call",
  partner: "Partner",
  advertisement: "Advertisement",
  other: "Other",
};

const dateTimeFormat = new Intl.DateTimeFormat("en-GB", {
  dateStyle: "medium",
  timeStyle: "short",
});

export function formatDateTime(iso: string): string {
  return dateTimeFormat.format(new Date(iso));
}

/** 1536 -> "1.5 KB" (file sizes). */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export const PROPERTY_TYPE_LABELS: Record<string, string> = {
  apartment: "Apartment",
  villa: "Villa",
  plot: "Plot",
  commercial: "Commercial",
};

const UNITS: Record<string, number> = { cr: 7, crore: 7, crores: 7, l: 5, lakh: 5, lakhs: 5, lac: 5, lacs: 5 };

/**
 * A budget as typed by people in India -> whole rupees, or null if it isn't one.
 * "12000000", "1,20,00,000", "1.2 Cr", "80 L", "80 lakh" -> integers. Done with digit strings,
 * never floating point, so "1.2 Cr" is exactly 12000000. Fractions of a rupee are refused.
 */
export function parseRupees(text: string): number | null {
  const cleaned = text.trim().toLowerCase().replace(/^₹|^rs\.?/, "").replace(/[,\s]/g, "");
  const match = /^(\d+)(?:\.(\d+))?([a-z]*)$/.exec(cleaned);
  if (!match) return null;
  const [, whole, fraction = "", unit] = match;
  const zeros = unit ? UNITS[unit] : 0;
  if (zeros === undefined || fraction.length > zeros) return null;
  const digits = (whole + fraction.padEnd(zeros, "0")).replace(/^0+(?=\d)/, "");
  const value = Number(digits);
  return Number.isSafeInteger(value) ? value : null;
}

/** 12000000 -> "₹1.2 Cr", 8000000 -> "₹80 L", 95000 -> "₹95,000". */
export function formatRupees(value: number): string {
  const short = (n: number, zeros: number, unit: string) => {
    const scaled = n / 10 ** zeros;
    return `₹${Number.isInteger(scaled) ? scaled : Number(scaled.toFixed(2))} ${unit}`;
  };
  if (value >= 10_000_000) return short(value, 7, "Cr");
  if (value >= 100_000) return short(value, 5, "L");
  return `₹${new Intl.NumberFormat("en-IN").format(value)}`;
}

/** "₹1.2 Cr – ₹1.5 Cr", "from ₹80 L", "up to ₹2 Cr", or "—". */
export function formatBudget(min: number | null | undefined, max: number | null | undefined): string {
  if (min != null && max != null)
    return min === max ? formatRupees(min) : `${formatRupees(min)} – ${formatRupees(max)}`;
  if (min != null) return `from ${formatRupees(min)}`;
  if (max != null) return `up to ${formatRupees(max)}`;
  return "—";
}

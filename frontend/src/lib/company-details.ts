import {
  COMPANY_INDUSTRIES,
  type CompanyDetails,
  type CompanyIndustry,
} from "@/lib/api-types";
import { errorText } from "@/lib/webcheck";

/**
 * Company details on a lead (BP-02, ADR 0026): plain words and the rows of the card, without a
 * server. The API decides everything again - who may ask, which website is read, which values
 * exist; the browser only names the FIELDS to keep, never their values.
 */

export const COMPANY_FIELDS = [
  "company_website",
  "company_industry",
  "company_size",
] as const;
export type CompanyField = (typeof COMPANY_FIELDS)[number];

const FIELD_LABELS: Record<CompanyField, string> = {
  company_website: "Website",
  company_industry: "Industry",
  company_size: "Employees",
};

function shown(field: CompanyField, value: string | null): string | null {
  if (!value) return null;
  if (field === "company_industry")
    return COMPANY_INDUSTRIES[value as CompanyIndustry] ?? value;
  return value;
}

export type CompanyRow = {
  field: CompanyField;
  label: string;
  current: string | null;
  suggested: string | null;
  /** A suggestion exists and differs from what the lead has: the only rows that can be ticked. */
  canApply: boolean;
};

/** One row per field: what the lead has, what the website suggests, and whether it can be saved. */
export function companyRows(details: CompanyDetails): CompanyRow[] {
  const latest = details.latest;
  return COMPANY_FIELDS.map((field) => {
    const raw = latest ? latest[field] : null;
    const now = details.current[field];
    return {
      field,
      label: FIELD_LABELS[field],
      current: shown(field, now),
      suggested: shown(field, raw),
      canApply: Boolean(raw) && raw !== now,
    };
  });
}

const VERDICTS: Record<string, string> = {
  found: "Found on the company's website",
  not_found: "The website was read, but it states no industry or size",
  unclear: "The website could not be read",
  error: "The website could not be checked",
};

export function lookupVerdict(verdict: string): string {
  return VERDICTS[verdict] ?? verdict;
}

const HOST_TEXTS: Record<string, string> = {
  no_source:
    "Add the company's website, or a work e-mail address, to the lead first.",
  ip_literal:
    "The website is an IP address; a company's name address is needed.",
  internal_name: "That is not a public website.",
  bad_name: "That is not a valid website name.",
  free_mail:
    "The e-mail address is from a free mail service; add the company's website to the lead.",
  denied: "That website cannot be checked.",
};

/** Why a stored lookup has no suggestions (its error code), in plain words. */
export function lookupErrorText(code: string | null | undefined): string {
  if (code?.startsWith("host_") && HOST_TEXTS[code.slice(5)])
    return HOST_TEXTS[code.slice(5)];
  if (code?.startsWith("status_"))
    return "The website answered with an error page.";
  return errorText(code);
}

const ASK_ERRORS: Record<string, string> = {
  company_details_unavailable:
    "Company details are switched off for your organisation. An administrator can switch them on under AI agents.",
  company_details_limit_reached:
    "You have asked for many look-ups recently. Try again in a while.",
  webcheck_disabled: "Web checks are switched off.",
  record_not_found: "You can't see this lead.",
};

const SAVE_ERRORS: Record<string, string> = {
  version_conflict:
    "Someone changed this lead after you opened it. Reload the page and choose again.",
  field_not_suggested: "Only fields with a suggestion can be saved.",
  company_details_not_found:
    "These suggestions are no longer available. Look up the company again.",
  record_not_found: "You can't see this lead.",
};

/** Why asking for a look-up was refused; the server's sentence when we have no better words. */
export function askErrorText(
  code: string | null | undefined,
  fallback: string,
): string {
  if (code?.startsWith("company_host_") && HOST_TEXTS[code.slice(13)])
    return HOST_TEXTS[code.slice(13)];
  return (code && ASK_ERRORS[code]) || fallback;
}

/** Why saving the chosen suggestions was refused. */
export function saveErrorText(
  code: string | null | undefined,
  fallback: string,
): string {
  return (code && SAVE_ERRORS[code]) || fallback;
}

export type ApplyCheck =
  | { ok: true; fields: CompanyField[]; version: number; evidenceId: string }
  | { ok: false; message: string };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** A first check of the save form; anything not one of the three fields is refused, not dropped. */
export function checkApply(input: {
  fields: string[];
  version: string;
  evidenceId: string;
}): ApplyCheck {
  const fields = input.fields;
  if (fields.length === 0)
    return { ok: false, message: "Tick at least one suggestion to save." };
  if (
    fields.some((f) => !(COMPANY_FIELDS as readonly string[]).includes(f)) ||
    new Set(fields).size !== fields.length
  )
    return { ok: false, message: "Only the suggested fields can be saved." };
  const version = Number(input.version);
  if (!Number.isInteger(version) || version < 1 || !UUID.test(input.evidenceId))
    return {
      ok: false,
      message: "The form is out of date. Reload the page and try again.",
    };
  return {
    ok: true,
    fields: fields as CompanyField[],
    version,
    evidenceId: input.evidenceId,
  };
}

/**
 * Branding of an organisation (ADR 0032, PD1): the shape the API returns and the few rules the
 * form applies before anything is sent. The API repeats every rule and decides; nothing here is a
 * security check. Texts are shown as plain text and the colour is only ever a six-digit hex value.
 */

export type Branding = {
  primary_color: string;
  about_text: string;
  terms_text: string;
  contact_line: string;
  footer_line: string;
  has_logo: boolean;
  logo_width: number | null;
  logo_height: number | null;
  version: number;
  updated_at: string | null;
  cleaned_fields: string[];
};

export const TEXT_LIMITS = {
  about_text: 1500,
  terms_text: 1500,
  contact_line: 200,
  footer_line: 200,
} as const;

export type TextField = keyof typeof TEXT_LIMITS;

export const FIELD_LABELS: Record<TextField, string> = {
  about_text: "About us",
  terms_text: "Standard terms",
  contact_line: "Contact line",
  footer_line: "Footer line",
};

export const LOGO_MAX_BYTES = 1_048_576;
export const LOGO_TYPES = ["image/png", "image/jpeg"] as const;

/** "#1F3A5F" or "1f3a5f" -> "1f3a5f"; anything else -> null. */
export function normalizeColor(value: string): string | null {
  const text = value.trim().replace(/^#/, "").toLowerCase();
  return /^[0-9a-f]{6}$/.test(text) ? text : null;
}

/** Black or white text, whichever reads better on the colour (WCAG luminance). */
export function readableTextColor(hex: string): "#111111" | "#ffffff" {
  const value = normalizeColor(hex) ?? "1f3a5f";
  const [r, g, b] = [0, 2, 4].map(
    (i) => parseInt(value.slice(i, i + 2), 16) / 255,
  );
  const lin = (c: number) =>
    c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  const luminance = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  return luminance > 0.179 ? "#111111" : "#ffffff";
}

export type BrandingValues = Record<"primary_color" | TextField, string>;

/** What the form can check before sending: the colour and the text lengths. */
export function checkBranding(
  values: BrandingValues,
):
  | { ok: true; color: string }
  | { ok: false; fieldErrors: Record<string, string> } {
  const fieldErrors: Record<string, string> = {};
  const color = normalizeColor(values.primary_color);
  if (!color)
    fieldErrors.primary_color = "Use six hex digits, for example 1F3A5F.";
  for (const field of Object.keys(TEXT_LIMITS) as TextField[]) {
    if (values[field].trim().length > TEXT_LIMITS[field])
      fieldErrors[field] = `At most ${TEXT_LIMITS[field]} characters.`;
  }
  return Object.keys(fieldErrors).length > 0
    ? { ok: false, fieldErrors }
    : { ok: true, color: color as string };
}

/** The file before it is sent: a PNG or JPEG of at most 1 MB. */
export function checkLogoFile(file: {
  name: string;
  size: number;
  type: string;
}): string | null {
  if (!file.name || file.size === 0) return "Choose a logo file.";
  if (!(LOGO_TYPES as readonly string[]).includes(file.type))
    return "The logo must be a PNG or a JPEG.";
  if (file.size > LOGO_MAX_BYTES) return "The logo can be at most 1 MB.";
  return null;
}

export function brandingErrorText(
  code: string | null,
  fallback: string,
): string {
  switch (code) {
    case "branding_color_invalid":
      return "The colour must be six hex digits, for example 1F3A5F.";
    case "branding_text_refused":
      return "One of the texts contains words that read like instructions to an AI. Write it in ordinary words.";
    case "branding_text_too_long":
      return "One of the texts is too long.";
    case "logo_type_not_allowed":
      return "The logo must be a PNG or a JPEG.";
    case "logo_too_large":
      return "The logo is too large: at most 1 MB and 2000 pixels on a side.";
    case "logo_too_small":
      return "The logo is too small: at least 16 pixels on a side.";
    case "logo_invalid":
      return "The file is not a readable picture.";
    case "logo_not_found":
      return "There is no logo to remove.";
    case "version_conflict":
      return "The branding was changed by someone else. Reload the page and try again.";
    default:
      return fallback;
  }
}

/** Fields where the server took something out (a link, markup, hidden characters), in words. */
export function cleanedNotice(fields: string[]): string | null {
  const names = fields
    .map((f) => FIELD_LABELS[f as TextField])
    .filter(Boolean)
    .join(", ");
  return names
    ? `Links, markup or hidden characters were removed from: ${names}.`
    : null;
}

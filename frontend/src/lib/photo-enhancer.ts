/**
 * Property photo enhancer (ADR 0039): types, words and the building of the adjustments the API
 * accepts. Display helpers only - the API refuses anything above a cap or off the list, whatever
 * this file sends.
 */

export type Enhancement = {
  id: string;
  original_document_id: string;
  status: "queued" | "ready" | "failed";
  failure_code: string | null;
  operations: Record<string, unknown>;
  applied: string[] | null;
  width: number | null;
  height: number | null;
  size_bytes: number | null;
  /** Chosen for proposal decks (ADR 0039, PE5). */
  in_decks: boolean;
  created_at: string;
  finished_at: string | null;
};

export type EnhancementPage = { items: Enhancement[]; caption: string };

/** Looking again while a copy is being made, in milliseconds. */
export const PHOTO_REFRESH_MS = 4000;
/** The preview waits for the slider to rest this long before it asks the server. */
export const PREVIEW_DELAY_MS = 450;

/** Required on every screen that shows or makes an adjusted copy (owner's decision, ADR 0039 Q5). */
export const PEOPLE_WARNING =
  "Check for people and number plates before sharing this photo.";
export const HONEST_NOTE =
  "An adjusted copy only changes how the camera's picture looks (brightness, colour, straightness, size). " +
  "It never adds or removes anything, and your original photo is always kept.";

/** Documents the enhancer can work on: JPEG and PNG (the documents module accepts no WebP). */
export const isPhoto = (contentType: string) =>
  contentType === "image/jpeg" || contentType === "image/png";

/** The sliders' ranges are the API's caps, so the screen cannot ask for more than it allows. */
export const LIMITS = {
  brightness: 30,
  contrast: 20,
  straighten: 5,
  /** Most that can be trimmed from one edge: the API needs 60 % of each side kept. */
  trim: 20,
} as const;

export const PRESETS: { value: string; label: string }[] = [
  { value: "original", label: "Full size (at most 4,000 pixels)" },
  { value: "brochure", label: "Brochure (2,000 pixels)" },
  { value: "whatsapp", label: "WhatsApp (1,280 pixels)" },
  { value: "thumbnail", label: "Thumbnail (400 pixels)" },
];

export const CORNERS: { value: string; label: string }[] = [
  { value: "bottom_right", label: "Bottom right" },
  { value: "bottom_left", label: "Bottom left" },
  { value: "top_right", label: "Top right" },
  { value: "top_left", label: "Top left" },
];

export type PhotoForm = {
  autoExposure: boolean;
  autoWhiteBalance: boolean;
  sharpen: boolean;
  brightness: number;
  contrast: number;
  straighten: number;
  trimLeft: number;
  trimTop: number;
  trimRight: number;
  trimBottom: number;
  preset: string;
  watermark: "none" | "text" | "logo";
  corner: string;
  watermarkText: string;
};

export const INITIAL_FORM: PhotoForm = {
  autoExposure: false,
  autoWhiteBalance: false,
  sharpen: false,
  brightness: 0,
  contrast: 0,
  straighten: 0,
  trimLeft: 0,
  trimTop: 0,
  trimRight: 0,
  trimBottom: 0,
  preset: "original",
  watermark: "none",
  corner: "bottom_right",
  watermarkText: "",
};

const clamp = (value: number, limit: number) =>
  Math.max(-limit, Math.min(limit, Number.isFinite(value) ? value : 0));

/**
 * The adjustments exactly as the API takes them. Values are kept inside the caps; anything the
 * person did not change is left out, so an untouched form sends `{ preset }` only.
 */
export function buildOperations(form: PhotoForm): Record<string, unknown> {
  const operations: Record<string, unknown> = { preset: form.preset };
  if (form.autoExposure) operations.auto_exposure = true;
  if (form.autoWhiteBalance) operations.auto_white_balance = true;
  if (form.sharpen) operations.sharpen = true;
  const brightness = Math.round(clamp(form.brightness, LIMITS.brightness));
  if (brightness) operations.brightness_percent = brightness;
  const contrast = Math.round(clamp(form.contrast, LIMITS.contrast));
  if (contrast) operations.contrast_percent = contrast;
  const straighten = clamp(form.straighten, LIMITS.straighten);
  if (straighten) operations.straighten_degrees = straighten;
  const trim = (value: number) =>
    Math.max(0, Math.min(LIMITS.trim, Number.isFinite(value) ? value : 0));
  const [left, top, right, bottom] = [
    trim(form.trimLeft),
    trim(form.trimTop),
    trim(form.trimRight),
    trim(form.trimBottom),
  ];
  if (left || top || right || bottom)
    operations.crop = [
      left / 100,
      top / 100,
      1 - right / 100,
      1 - bottom / 100,
    ];
  if (form.watermark === "logo")
    operations.watermark = { kind: "logo", corner: form.corner };
  if (form.watermark === "text" && form.watermarkText.trim())
    operations.watermark = {
      kind: "text",
      corner: form.corner,
      text: form.watermarkText.trim().slice(0, 40),
    };
  return operations;
}

/** The API's stable error codes in plain words. */
export function photoErrorText(code: string | null, fallback: string): string {
  switch (code) {
    case "photo_enhancer_unavailable":
      return "The photo enhancer is switched off for your organisation. An administrator can switch it on under AI agents.";
    case "photo_operation_too_strong":
      return "One of the adjustments is stronger than allowed. Move the slider back a little.";
    case "photo_operation_unknown":
      return "That adjustment is not available.";
    case "photo_preset_unknown":
      return "That size is not available.";
    case "photo_watermark_logo_missing":
      return "Your organisation has no logo yet. Add one under Branding, or use a text watermark.";
    case "photo_watermark_text_invalid":
    case "photo_watermark_refused":
      return "The watermark text is not allowed. Use 1 to 40 plain characters.";
    case "photo_not_an_image":
      return "Only JPEG and PNG photos can be adjusted.";
    case "photo_too_large":
      return "This photo is too large to adjust here.";
    case "photo_took_too_long":
      return "The photo took too long to adjust. Try a smaller size.";
    case "photo_limit_reached":
      return "Too many photos were adjusted, or this photo already has the most copies allowed. Delete one or try later.";
    case "photo_copy_not_ready":
      return "Only a finished copy can be chosen for decks.";
    case "photo_not_found":
    case "photo_copy_not_found":
      return "That photo was not found, or you may not see it.";
    case "forbidden":
      return "You are not allowed to adjust photos.";
    default:
      return fallback;
  }
}

/** Why a copy that could not be made failed, in words. */
export function failureText(code: string | null): string {
  switch (code) {
    case "too_large":
      return "The photo is too large to adjust.";
    case "not_an_image":
    case "type_not_allowed":
    case "unreadable":
      return "The photo could not be read.";
    case "took_too_long":
      return "The photo took too long to adjust.";
    case "watermark_logo_missing":
      return "The organisation's logo was not available.";
    case "photo_enhancer_off":
      return "The photo enhancer was switched off.";
    default:
      return "The copy could not be made.";
  }
}

export const isWorking = (copies: Enhancement[]) =>
  copies.some((copy) => copy.status === "queued");

export function copyStateText(copy: Enhancement): string {
  if (copy.status === "queued") return "Being made…";
  if (copy.status === "failed") return failureText(copy.failure_code);
  return "Enhanced copy";
}

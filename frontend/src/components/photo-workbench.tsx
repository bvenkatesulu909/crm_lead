"use client";

import {
  useActionState,
  useEffect,
  useMemo,
  useState,
  useTransition,
} from "react";

import { createEnhancement } from "@/app/(app)/photos/actions";
import { ErrorAlert, buttonClass } from "@/components/ui";
import { initialDialogState } from "@/lib/dialog-state";
import {
  CORNERS,
  HONEST_NOTE,
  INITIAL_FORM,
  LIMITS,
  PEOPLE_WARNING,
  PRESETS,
  PREVIEW_DELAY_MS,
  buildOperations,
  photoErrorText,
  type PhotoForm,
} from "@/lib/photo-enhancer";

type Preview =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "ready"; url: string }
  | { state: "error"; message: string };

function Slider({
  label,
  value,
  min,
  max,
  step = 1,
  unit,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit: string;
  onChange: (value: number) => void;
}) {
  return (
    <label className="block text-sm text-slate-700">
      <span className="flex justify-between">
        <span>{label}</span>
        <span className="text-slate-500">
          {value > 0 && min < 0 ? "+" : ""}
          {value}
          {unit}
        </span>
      </span>
      <input
        type="range"
        className="mt-1 w-full"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

/**
 * Adjust one photo (ADR 0039): sliders for the allowed adjustments, a preview made by the server
 * (the same code as the final copy, from a small working copy) and a button that asks for the real
 * copy. The sliders stop at the API's caps; the API checks again. The browser sends only the
 * adjustments - never a token - to this app's own route handlers.
 */
export function PhotoWorkbench({
  documentId,
  fileName,
  previewDelayMs = PREVIEW_DELAY_MS,
}: {
  documentId: string;
  fileName: string;
  previewDelayMs?: number;
}) {
  const [form, setForm] = useState<PhotoForm>(INITIAL_FORM);
  const [preview, setPreview] = useState<Preview>({ state: "idle" });
  const operations = useMemo(() => buildOperations(form), [form]);
  const key = JSON.stringify(operations);
  const [state, run, pending] = useActionState(
    (previous: typeof initialDialogState) =>
      createEnhancement(documentId, operations, previous),
    initialDialogState,
  );
  // Not <form action>: React empties a form after its action, which would also reset the sliders
  // after a refusal. The settings are state here, and a refusal must keep them.
  const [, startTransition] = useTransition();
  const set = <K extends keyof PhotoForm>(name: K, value: PhotoForm[K]) =>
    setForm((current) => ({ ...current, [name]: value }));

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;
    const timer = setTimeout(async () => {
      setPreview({ state: "loading" });
      try {
        const response = await fetch(`/photos/${documentId}/preview`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ operations: JSON.parse(key) }),
          signal: controller.signal,
        });
        if (!response.ok) {
          const problem = (await response.json().catch(() => null)) as {
            detail?: string;
            code?: string;
          } | null;
          setPreview({
            state: "error",
            message: photoErrorText(
              problem?.code ?? null,
              problem?.detail ?? "The preview could not be made.",
            ),
          });
          return;
        }
        objectUrl = URL.createObjectURL(await response.blob());
        setPreview({ state: "ready", url: objectUrl });
      } catch (error) {
        if ((error as Error).name !== "AbortError")
          setPreview({
            state: "error",
            message: "The preview could not be made.",
          });
      }
    }, previewDelayMs);
    return () => {
      clearTimeout(timer);
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [documentId, key, previewDelayMs]);

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        startTransition(() => run());
      }}
      className="grid gap-6 lg:grid-cols-2"
    >
      <div className="space-y-4">
        <p
          role="note"
          data-testid="people-warning"
          className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900"
        >
          {PEOPLE_WARNING}
        </p>
        <fieldset className="space-y-2">
          <legend className="text-sm font-semibold text-slate-800">
            Quick fixes
          </legend>
          {(
            [
              ["autoExposure", "Even out the exposure"],
              ["autoWhiteBalance", "Correct a colour cast"],
              ["sharpen", "Sharpen slightly"],
            ] as const
          ).map(([name, label]) => (
            <label key={name} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form[name]}
                onChange={(event) => set(name, event.target.checked)}
              />
              {label}
            </label>
          ))}
        </fieldset>
        <fieldset className="space-y-3">
          <legend className="text-sm font-semibold text-slate-800">
            Adjust
          </legend>
          <Slider
            label="Brightness"
            value={form.brightness}
            min={-LIMITS.brightness}
            max={LIMITS.brightness}
            unit=" %"
            onChange={(v) => set("brightness", v)}
          />
          <Slider
            label="Contrast"
            value={form.contrast}
            min={-LIMITS.contrast}
            max={LIMITS.contrast}
            unit=" %"
            onChange={(v) => set("contrast", v)}
          />
          <Slider
            label="Straighten"
            value={form.straighten}
            min={-LIMITS.straighten}
            max={LIMITS.straighten}
            step={0.5}
            unit="°"
            onChange={(v) => set("straighten", v)}
          />
        </fieldset>
        <fieldset className="space-y-3">
          <legend className="text-sm font-semibold text-slate-800">
            Crop (trim each edge)
          </legend>
          <Slider
            label="Left"
            value={form.trimLeft}
            min={0}
            max={LIMITS.trim}
            unit=" %"
            onChange={(v) => set("trimLeft", v)}
          />
          <Slider
            label="Top"
            value={form.trimTop}
            min={0}
            max={LIMITS.trim}
            unit=" %"
            onChange={(v) => set("trimTop", v)}
          />
          <Slider
            label="Right"
            value={form.trimRight}
            min={0}
            max={LIMITS.trim}
            unit=" %"
            onChange={(v) => set("trimRight", v)}
          />
          <Slider
            label="Bottom"
            value={form.trimBottom}
            min={0}
            max={LIMITS.trim}
            unit=" %"
            onChange={(v) => set("trimBottom", v)}
          />
        </fieldset>
        <div className="space-y-2">
          <label className="block text-sm text-slate-700">
            Size
            <select
              className="mt-1 block w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
              value={form.preset}
              onChange={(event) => set("preset", event.target.value)}
            >
              {PRESETS.map((preset) => (
                <option key={preset.value} value={preset.value}>
                  {preset.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm text-slate-700">
            Watermark
            <select
              className="mt-1 block w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
              value={form.watermark}
              onChange={(event) =>
                set("watermark", event.target.value as PhotoForm["watermark"])
              }
            >
              <option value="none">None</option>
              <option value="text">Text</option>
              <option value="logo">Our logo</option>
            </select>
          </label>
          {form.watermark !== "none" && (
            <label className="block text-sm text-slate-700">
              Corner
              <select
                className="mt-1 block w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                value={form.corner}
                onChange={(event) => set("corner", event.target.value)}
              >
                {CORNERS.map((corner) => (
                  <option key={corner.value} value={corner.value}>
                    {corner.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          {form.watermark === "text" && (
            <label className="block text-sm text-slate-700">
              Watermark text
              <input
                type="text"
                maxLength={40}
                className="mt-1 block w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                value={form.watermarkText}
                onChange={(event) => set("watermarkText", event.target.value)}
              />
            </label>
          )}
        </div>
      </div>

      <div className="space-y-3">
        <div
          className="flex min-h-48 items-center justify-center rounded-md border border-slate-200 bg-slate-50 p-2"
          aria-live="polite"
        >
          {preview.state === "ready" ? (
            // eslint-disable-next-line @next/next/no-img-element -- a blob made for this page
            <img
              src={preview.url}
              alt={`Preview of ${fileName} with your adjustments`}
              className="max-h-96 max-w-full"
            />
          ) : preview.state === "error" ? (
            <p role="alert" className="text-sm text-red-700">
              {preview.message}
            </p>
          ) : (
            <p className="text-sm text-slate-500">
              {preview.state === "loading"
                ? "Making the preview…"
                : "The preview appears here."}
            </p>
          )}
        </div>
        <p className="text-xs text-slate-500">{HONEST_NOTE}</p>
        {state.error && (
          <ErrorAlert
            title="The copy could not be asked for"
            error={state.error}
          />
        )}
        <button
          type="submit"
          disabled={pending}
          className={buttonClass("primary")}
        >
          {pending ? "Sending…" : "Make enhanced copy"}
        </button>
      </div>
    </form>
  );
}

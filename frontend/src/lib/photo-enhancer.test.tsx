import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  chooseForDecks,
  createEnhancement,
  deleteEnhancement,
} from "@/app/(app)/photos/actions";
import { PhotoCopies } from "@/components/photo-copies";
import { PhotoWorkbench } from "@/components/photo-workbench";
import { ApiError } from "@/lib/api-error";
import { initialDialogState } from "@/lib/dialog-state";
import { canEnhancePhotos } from "@/lib/permissions";
import {
  INITIAL_FORM,
  LIMITS,
  PEOPLE_WARNING,
  PHOTO_REFRESH_MS,
  buildOperations,
  copyStateText,
  failureText,
  isPhoto,
  isWorking,
  photoErrorText,
  type Enhancement,
} from "@/lib/photo-enhancer";

const apiFetch = vi.fn();
const apiStream = vi.fn();
vi.mock("@/lib/server/api", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
  apiStream: (...a: unknown[]) => apiStream(...a),
}));
const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`REDIRECT:${to}`);
  },
  useRouter: () => ({ refresh }),
}));

const DOC = "11111111-1111-4111-8111-111111111111";
const COPY = "22222222-2222-4222-8222-222222222222";

function copy(over: Partial<Enhancement> = {}): Enhancement {
  return {
    id: COPY,
    original_document_id: DOC,
    status: "ready",
    failure_code: null,
    operations: {},
    applied: ["Brightness +12 %", "Resized to at most 4000 pixels"],
    width: 400,
    height: 300,
    size_bytes: 24_000,
    in_decks: false,
    created_at: "2026-11-22T09:00:00Z",
    finished_at: "2026-11-22T09:00:03Z",
    ...over,
  };
}

function problem(status: number, code: string) {
  return new ApiError(status, {
    title: "x",
    status,
    detail: "Server words",
    code,
    request_id: "r",
  });
}

beforeEach(() => {
  apiFetch.mockReset();
  apiStream.mockReset();
  refresh.mockReset();
});

describe("buildOperations", () => {
  it("an untouched form asks for nothing but the size", () => {
    expect(buildOperations(INITIAL_FORM)).toEqual({ preset: "original" });
  });

  it("sends only what was changed, in the API's names", () => {
    expect(
      buildOperations({
        ...INITIAL_FORM,
        autoExposure: true,
        autoWhiteBalance: true,
        sharpen: true,
        brightness: 12,
        contrast: -5,
        straighten: -1.5,
        preset: "whatsapp",
      }),
    ).toEqual({
      preset: "whatsapp",
      auto_exposure: true,
      auto_white_balance: true,
      sharpen: true,
      brightness_percent: 12,
      contrast_percent: -5,
      straighten_degrees: -1.5,
    });
  });

  it("never goes above the API's caps", () => {
    const ops = buildOperations({
      ...INITIAL_FORM,
      brightness: 500,
      contrast: -500,
      straighten: 99,
      trimLeft: 90,
    });
    expect(ops.brightness_percent).toBe(LIMITS.brightness);
    expect(ops.contrast_percent).toBe(-LIMITS.contrast);
    expect(ops.straighten_degrees).toBe(LIMITS.straighten);
    expect((ops.crop as number[])[0]).toBeCloseTo(0.2);
  });

  it("a crop always keeps at least 60 % of each side", () => {
    const ops = buildOperations({
      ...INITIAL_FORM,
      trimLeft: 20,
      trimRight: 20,
      trimTop: 20,
      trimBottom: 20,
    });
    const [l, t, r, b] = ops.crop as number[];
    expect(r - l).toBeGreaterThanOrEqual(0.6 - 1e-9);
    expect(b - t).toBeGreaterThanOrEqual(0.6 - 1e-9);
    expect(buildOperations({ ...INITIAL_FORM, trimTop: 10 }).crop).toEqual([
      0, 0.1, 1, 1,
    ]);
  });

  it("builds the watermark, trims its text and ignores an empty one", () => {
    expect(
      buildOperations({
        ...INITIAL_FORM,
        watermark: "text",
        watermarkText: "  Banyan Builders  ",
        corner: "top_left",
      }).watermark,
    ).toEqual({ kind: "text", corner: "top_left", text: "Banyan Builders" });
    expect(
      buildOperations({
        ...INITIAL_FORM,
        watermark: "text",
        watermarkText: " ",
      }).watermark,
    ).toBeUndefined();
    expect(
      buildOperations({ ...INITIAL_FORM, watermark: "logo" }).watermark,
    ).toEqual({ kind: "logo", corner: "bottom_right" });
    expect(
      (
        buildOperations({
          ...INITIAL_FORM,
          watermark: "text",
          watermarkText: "x".repeat(80),
        }).watermark as { text: string }
      ).text,
    ).toHaveLength(40);
  });

  it("offers nothing that could add or remove things from the scene", () => {
    const names = Object.keys(
      buildOperations({
        ...INITIAL_FORM,
        autoExposure: true,
        autoWhiteBalance: true,
        sharpen: true,
        brightness: 1,
        contrast: 1,
        straighten: 1,
        trimLeft: 1,
        watermark: "logo",
      }),
    ).sort();
    expect(names).toEqual(
      [
        "auto_exposure",
        "auto_white_balance",
        "brightness_percent",
        "contrast_percent",
        "crop",
        "preset",
        "sharpen",
        "straighten_degrees",
        "watermark",
      ].sort(),
    );
  });
});

describe("words and permissions", () => {
  it("knows which documents are photos", () => {
    expect(isPhoto("image/jpeg")).toBe(true);
    expect(isPhoto("image/png")).toBe(true);
    expect(isPhoto("image/gif")).toBe(false);
    expect(isPhoto("application/pdf")).toBe(false);
  });

  it("needs both permissions to show the tool", () => {
    expect(
      canEnhancePhotos({ permissions: ["photo:enhance", "document:write"] }),
    ).toBe(true);
    expect(canEnhancePhotos({ permissions: ["photo:enhance"] })).toBe(false);
    expect(canEnhancePhotos({ permissions: ["document:write"] })).toBe(false);
  });

  it("explains the API's codes in plain words", () => {
    expect(photoErrorText("photo_enhancer_unavailable", "x")).toMatch(
      /switched off/,
    );
    expect(photoErrorText("photo_operation_too_strong", "x")).toMatch(
      /stronger than allowed/,
    );
    expect(photoErrorText("photo_watermark_logo_missing", "x")).toMatch(
      /Branding/,
    );
    expect(photoErrorText("photo_limit_reached", "x")).toMatch(/Delete one/);
    expect(photoErrorText("something_else", "Server words")).toBe(
      "Server words",
    );
    expect(failureText("too_large")).toMatch(/too large/);
    expect(failureText("unreadable")).toMatch(/could not be read/);
    expect(failureText("whatever")).toMatch(/could not be made/);
  });

  it("says where each copy stands", () => {
    expect(copyStateText(copy({ status: "queued" }))).toMatch(/Being made/);
    expect(copyStateText(copy())).toBe("Enhanced copy");
    expect(
      copyStateText(copy({ status: "failed", failure_code: "took_too_long" })),
    ).toMatch(/too long/);
    expect(isWorking([copy(), copy({ status: "queued" })])).toBe(true);
    expect(isWorking([copy()])).toBe(false);
  });
});

describe("Server Actions", () => {
  it("send only the photo and the adjustments", async () => {
    apiFetch.mockResolvedValue({});
    await expect(
      createEnhancement(DOC, { brightness_percent: 5 }, initialDialogState),
    ).rejects.toThrow(`REDIRECT:/photos/${DOC}?done=queued`);
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe("/photo-enhancer/enhancements");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      document_id: DOC,
      operations: { brightness_percent: 5 },
    });
  });

  it("show the API's refusal in plain words and keep the page", async () => {
    apiFetch.mockRejectedValue(problem(422, "photo_operation_too_strong"));
    const state = await createEnhancement(DOC, {}, initialDialogState);
    expect(state.attempt).toBe(1);
    expect(state.error?.message).toMatch(/stronger than allowed/);
  });

  it("refuse an id that is not an id before calling the API", async () => {
    await expect(
      createEnhancement("not-an-id", {}, initialDialogState),
    ).rejects.toThrow("invalid document id");
    await expect(
      deleteEnhancement(DOC, "nope", initialDialogState),
    ).rejects.toThrow("invalid id");
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("choosing for decks sends only the choice and answers in words", async () => {
    apiFetch.mockResolvedValue({});
    expect(await chooseForDecks(COPY, true)).toEqual({ error: null });
    expect(JSON.parse(apiFetch.mock.calls[0][1].body)).toEqual({
      in_decks: true,
    });
    apiFetch.mockRejectedValue(problem(404, "photo_copy_not_found"));
    expect((await chooseForDecks(COPY, false)).error).toMatch(/not found/);
    await expect(chooseForDecks("nope", true)).rejects.toThrow("invalid id");
  });

  it("delete one copy and go back to the photo", async () => {
    apiFetch.mockResolvedValue(undefined);
    await expect(
      deleteEnhancement(DOC, COPY, initialDialogState),
    ).rejects.toThrow(`REDIRECT:/photos/${DOC}?done=deleted`);
    expect(apiFetch.mock.calls[0][0]).toBe(
      `/photo-enhancer/enhancements/${COPY}`,
    );
    expect(apiFetch.mock.calls[0][1].method).toBe("DELETE");
  });
});

describe("PhotoCopies", () => {
  const caption = "Photo adjusted for brightness and colour";

  it("a ready copy is badged Enhanced, lists what was done and offers the original", () => {
    render(
      <PhotoCopies
        documentId={DOC}
        copies={[copy()]}
        caption={caption}
        canDelete
      />,
    );
    expect(screen.getByText("Enhanced")).toBeInTheDocument();
    expect(screen.getByText("Brightness +12 %")).toBeInTheDocument();
    expect(screen.getByText(/Show original/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download copy" })).toHaveAttribute(
      "href",
      `/photos/copies/${COPY}/download`,
    );
    expect(screen.getByText(new RegExp(caption))).toBeInTheDocument();
    expect(screen.getByText(new RegExp(PEOPLE_WARNING))).toBeInTheDocument();
    expect(screen.getByAltText("Original photo")).toHaveAttribute(
      "src",
      `/documents/${DOC}/download`,
    );
  });

  it("a waiting copy has no badge and no download", () => {
    render(
      <PhotoCopies
        documentId={DOC}
        copies={[copy({ status: "queued", applied: null, size_bytes: null })]}
        caption={caption}
        canDelete
      />,
    );
    expect(screen.queryByText("Enhanced")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Download/ })).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent(/Being made/);
  });

  it("a failed copy says why", () => {
    render(
      <PhotoCopies
        documentId={DOC}
        copies={[
          copy({ status: "failed", failure_code: "too_large", applied: null }),
        ]}
        caption={caption}
        canDelete
      />,
    );
    expect(screen.getByText(/too large to adjust/)).toBeInTheDocument();
    expect(screen.queryByText("Enhanced")).not.toBeInTheDocument();
  });

  it("without the right to delete there is no delete button", () => {
    render(
      <PhotoCopies
        documentId={DOC}
        copies={[copy()]}
        caption={caption}
        canDelete={false}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "Delete copy" }),
    ).not.toBeInTheDocument();
  });

  it("a ready copy can be chosen for decks, and the choice is saved", async () => {
    apiFetch.mockResolvedValue({});
    render(
      <PhotoCopies
        documentId={DOC}
        copies={[copy()]}
        caption={caption}
        canDelete
      />,
    );
    const box = screen.getByLabelText("Use in proposal decks");
    expect(box).not.toBeChecked();
    await userEvent.click(box);
    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe(`/photo-enhancer/enhancements/${COPY}`);
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({ in_decks: true });
    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it("shows a copy already chosen as ticked and explains the choice", () => {
    render(
      <PhotoCopies
        documentId={DOC}
        copies={[copy({ in_decks: true })]}
        caption={caption}
        canDelete
      />,
    );
    expect(screen.getByLabelText("Use in proposal decks")).toBeChecked();
    expect(
      screen.getByText(/only when .*Use in proposal decks.* is ticked/),
    ).toBeInTheDocument();
  });

  it("explains a refused choice and leaves the page as it was", async () => {
    apiFetch.mockRejectedValue(problem(409, "photo_copy_not_ready"));
    render(
      <PhotoCopies
        documentId={DOC}
        copies={[copy()]}
        caption={caption}
        canDelete
      />,
    );
    await userEvent.click(screen.getByLabelText("Use in proposal decks"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/finished copy/);
    expect(refresh).not.toHaveBeenCalled();
  });

  it("a waiting copy and a reader without rights get no deck choice", () => {
    const { rerender } = render(
      <PhotoCopies
        documentId={DOC}
        copies={[copy({ status: "queued", applied: null })]}
        caption={caption}
        canDelete
      />,
    );
    expect(screen.queryByLabelText("Use in proposal decks")).toBeNull();
    rerender(
      <PhotoCopies
        documentId={DOC}
        copies={[copy()]}
        caption={caption}
        canDelete={false}
      />,
    );
    expect(screen.queryByLabelText("Use in proposal decks")).toBeNull();
  });

  it("with no copies it explains how to make one", () => {
    render(
      <PhotoCopies documentId={DOC} copies={[]} caption={caption} canDelete />,
    );
    expect(screen.getByText(/No adjusted copies yet/)).toBeInTheDocument();
  });

  describe("while a copy is being made", () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it("looks again every few seconds, and stops when nothing is waiting", () => {
      const { rerender } = render(
        <PhotoCopies
          documentId={DOC}
          copies={[copy({ status: "queued" })]}
          caption={caption}
          canDelete
        />,
      );
      act(() => {
        vi.advanceTimersByTime(PHOTO_REFRESH_MS * 2 + 10);
      });
      expect(refresh).toHaveBeenCalledTimes(2);
      rerender(
        <PhotoCopies
          documentId={DOC}
          copies={[copy()]}
          caption={caption}
          canDelete
        />,
      );
      refresh.mockClear();
      act(() => {
        vi.advanceTimersByTime(PHOTO_REFRESH_MS * 3);
      });
      expect(refresh).not.toHaveBeenCalled();
    });
  });
});

describe("PhotoWorkbench", () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = URL.createObjectURL;
  afterEach(() => {
    globalThis.fetch = originalFetch;
    URL.createObjectURL = originalUrl;
  });

  function previewOk() {
    URL.createObjectURL = vi.fn(() => "blob:preview");
    URL.revokeObjectURL = vi.fn();
    globalThis.fetch = vi.fn(async () =>
      Promise.resolve(
        new Response(new Blob(["x"], { type: "image/jpeg" }), {
          status: 200,
          headers: { "Content-Type": "image/jpeg" },
        }),
      ),
    ) as unknown as typeof fetch;
  }

  it("always shows the warning about people and number plates", () => {
    previewOk();
    render(
      <PhotoWorkbench
        documentId={DOC}
        fileName="living.jpg"
        previewDelayMs={1}
      />,
    );
    expect(screen.getByTestId("people-warning")).toHaveTextContent(
      PEOPLE_WARNING,
    );
  });

  it("the sliders stop at the API's caps", () => {
    previewOk();
    render(
      <PhotoWorkbench
        documentId={DOC}
        fileName="living.jpg"
        previewDelayMs={1}
      />,
    );
    const slider = (name: string) =>
      screen.getByLabelText(new RegExp(`^${name}`)) as HTMLInputElement;
    expect(slider("Brightness").max).toBe(String(LIMITS.brightness));
    expect(slider("Brightness").min).toBe(String(-LIMITS.brightness));
    expect(slider("Contrast").max).toBe(String(LIMITS.contrast));
    expect(slider("Straighten").max).toBe(String(LIMITS.straighten));
    expect(slider("Left").max).toBe(String(LIMITS.trim));
  });

  it("shows the server's preview and sends only the adjustments, never a token", async () => {
    previewOk();
    render(
      <PhotoWorkbench
        documentId={DOC}
        fileName="living.jpg"
        previewDelayMs={1}
      />,
    );
    const img = await screen.findByAltText(/Preview of living.jpg/);
    expect(img).toHaveAttribute("src", "blob:preview");
    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock
      .calls[0];
    expect(url).toBe(`/photos/${DOC}/preview`);
    expect(JSON.parse(init.body)).toEqual({
      operations: { preset: "original" },
    });
    expect(JSON.stringify(init.headers)).not.toMatch(/authorization/i);
  });

  it("asks for a new preview when a slider moves", async () => {
    previewOk();
    render(
      <PhotoWorkbench
        documentId={DOC}
        fileName="living.jpg"
        previewDelayMs={1}
      />,
    );
    await screen.findByAltText(/Preview of/);
    const slider = screen.getByLabelText(/^Brightness/);
    // fireEvent-like change through userEvent is awkward for ranges: set the value directly.
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(slider, { target: { value: "20" } });
    await waitFor(() => {
      const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
      expect(JSON.parse(calls[calls.length - 1][1].body)).toEqual({
        operations: { preset: "original", brightness_percent: 20 },
      });
    });
  });

  it("explains a refused preview in plain words", async () => {
    globalThis.fetch = vi.fn(async () =>
      Promise.resolve(
        Response.json(
          { detail: "Server words", code: "photo_enhancer_unavailable" },
          { status: 503 },
        ),
      ),
    ) as unknown as typeof fetch;
    render(
      <PhotoWorkbench
        documentId={DOC}
        fileName="living.jpg"
        previewDelayMs={1}
      />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/switched off/);
  });

  it("asks for the real copy with the same adjustments", async () => {
    previewOk();
    apiFetch.mockRejectedValue(problem(429, "photo_limit_reached"));
    render(
      <PhotoWorkbench
        documentId={DOC}
        fileName="living.jpg"
        previewDelayMs={1}
      />,
    );
    await userEvent.click(screen.getByLabelText("Even out the exposure"));
    await userEvent.click(
      screen.getByRole("button", { name: "Make enhanced copy" }),
    );
    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    expect(JSON.parse(apiFetch.mock.calls[0][1].body)).toEqual({
      document_id: DOC,
      operations: { preset: "original", auto_exposure: true },
    });
  });

  it("shows a refusal of the real request and keeps the settings", async () => {
    previewOk();
    apiFetch.mockRejectedValue(problem(429, "photo_limit_reached"));
    render(
      <PhotoWorkbench
        documentId={DOC}
        fileName="living.jpg"
        previewDelayMs={1}
      />,
    );
    await userEvent.click(screen.getByLabelText("Sharpen slightly"));
    await userEvent.click(
      screen.getByRole("button", { name: "Make enhanced copy" }),
    );
    expect(await screen.findByText(/Delete one/)).toBeInTheDocument();
    expect(screen.getByLabelText("Sharpen slightly")).toBeChecked();
  });
});

describe("the preview route", () => {
  it("passes the adjustments on and returns the picture without caching", async () => {
    apiStream.mockResolvedValue(
      new Response("JPEGDATA", {
        status: 200,
        headers: { "Content-Type": "image/jpeg" },
      }),
    );
    const { POST } = await import("@/app/(app)/photos/[id]/preview/route");
    const response = await POST(
      new Request("http://x/photos/1/preview", {
        method: "POST",
        body: JSON.stringify({ operations: { brightness_percent: 5 } }),
      }) as never,
      { params: Promise.resolve({ id: DOC }) } as never,
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("image/jpeg");
    expect(response.headers.get("cache-control")).toMatch(/no-store/);
    expect(apiStream).toHaveBeenCalledWith("/photo-enhancer/previews", {
      document_id: DOC,
      operations: { brightness_percent: 5 },
    });
  });

  it("passes a refusal on with its code and refuses a bad id", async () => {
    apiStream.mockResolvedValue(
      Response.json(
        { detail: "Too many", code: "photo_limit_reached" },
        { status: 429 },
      ),
    );
    const { POST } = await import("@/app/(app)/photos/[id]/preview/route");
    const refused = await POST(
      new Request("http://x", { method: "POST", body: "{}" }) as never,
      { params: Promise.resolve({ id: DOC }) } as never,
    );
    expect(refused.status).toBe(429);
    expect(await refused.json()).toEqual({
      detail: "Too many",
      code: "photo_limit_reached",
    });
    apiStream.mockClear();
    const bad = await POST(
      new Request("http://x", { method: "POST", body: "{}" }) as never,
      { params: Promise.resolve({ id: "not-an-id" }) } as never,
    );
    expect(bad.status).toBe(404);
    expect(apiStream).not.toHaveBeenCalled();
  });
});

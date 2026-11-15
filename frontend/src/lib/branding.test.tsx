import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  removeLogo,
  saveBranding,
  uploadLogo,
} from "@/app/(app)/branding/actions";
import {
  BrandingForm,
  CoverPreview,
  LogoPanel,
} from "@/components/branding-views";
import { ApiError } from "@/lib/api-error";
import {
  LOGO_MAX_BYTES,
  brandingErrorText,
  checkBranding,
  checkLogoFile,
  cleanedNotice,
  normalizeColor,
  readableTextColor,
  type Branding,
} from "@/lib/branding";
import { initialFormState } from "@/lib/form-state";
import { canManageBranding, navigationFor } from "@/lib/permissions";

const apiFetch = vi.fn();
vi.mock("@/lib/server/api", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}));
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`REDIRECT:${to}`);
  },
}));

const BRANDING: Branding = {
  primary_color: "1f3a5f",
  about_text: "We build homes.",
  terms_text: "30 days.",
  contact_line: "sales@example.test",
  footer_line: "Acme Homes",
  has_logo: false,
  logo_width: null,
  logo_height: null,
  version: 3,
  updated_at: "2026-11-13T09:00:00Z",
  cleaned_fields: [],
};

function problem(status: number, code: string) {
  return new ApiError(status, {
    title: "x",
    status,
    detail: "Server words",
    code,
    request_id: "r",
  });
}

function form(values: Record<string, string>) {
  const data = new FormData();
  for (const [k, v] of Object.entries(values)) data.set(k, v);
  return data;
}

const FIELDS = {
  primary_color: "#1F3A5F",
  about_text: "About",
  terms_text: "Terms",
  contact_line: "Contact",
  footer_line: "Footer",
};

beforeEach(() => apiFetch.mockReset());

describe("helpers", () => {
  it("a colour is six hex digits, with or without #", () => {
    expect(normalizeColor("#1F3A5F")).toBe("1f3a5f");
    expect(normalizeColor(" 1f3a5f ")).toBe("1f3a5f");
    for (const bad of ["", "fff", "12345", "gggggg", "##1f3a5f", "red"])
      expect(normalizeColor(bad)).toBeNull();
  });

  it("text on a dark colour is white and on a light one black", () => {
    expect(readableTextColor("1f3a5f")).toBe("#ffffff");
    expect(readableTextColor("ffffff")).toBe("#111111");
    expect(readableTextColor("ffeb3b")).toBe("#111111"); // a bright yellow needs dark text
    expect(readableTextColor("808080")).toBe("#111111");
    expect(readableTextColor("606060")).toBe("#ffffff");
    expect(readableTextColor("not a colour")).toBe("#ffffff"); // the default colour
  });

  it("the form checks the colour and the text lengths before sending", () => {
    expect(
      checkBranding({
        primary_color: "1F3A5F",
        about_text: "",
        terms_text: "",
        contact_line: "",
        footer_line: "",
      }),
    ).toEqual({ ok: true, color: "1f3a5f" });
    const bad = checkBranding({
      primary_color: "red",
      about_text: "x".repeat(1501),
      terms_text: "",
      contact_line: "y".repeat(201),
      footer_line: "",
    });
    expect(bad.ok).toBe(false);
    if (!bad.ok)
      expect(Object.keys(bad.fieldErrors).sort()).toEqual([
        "about_text",
        "contact_line",
        "primary_color",
      ]);
  });

  it("a logo file must be a PNG or JPEG of at most 1 MB", () => {
    const ok = { name: "a.png", size: 1000, type: "image/png" };
    expect(checkLogoFile(ok)).toBeNull();
    expect(checkLogoFile({ ...ok, type: "image/jpeg" })).toBeNull();
    expect(checkLogoFile({ ...ok, type: "image/gif" })).toMatch(
      /PNG or a JPEG/,
    );
    expect(checkLogoFile({ ...ok, type: "image/svg+xml" })).toMatch(
      /PNG or a JPEG/,
    );
    expect(checkLogoFile({ ...ok, size: LOGO_MAX_BYTES + 1 })).toMatch(/1 MB/);
    expect(checkLogoFile({ ...ok, size: 0 })).toMatch(/Choose/);
    expect(checkLogoFile({ ...ok, name: "" })).toMatch(/Choose/);
  });

  it("known error codes become sentences and others keep the server's words", () => {
    expect(brandingErrorText("branding_text_refused", "x")).toMatch(
      /instructions/,
    );
    expect(brandingErrorText("logo_too_large", "x")).toMatch(/1 MB/);
    expect(brandingErrorText("version_conflict", "x")).toMatch(/someone else/);
    expect(brandingErrorText("other", "fallback")).toBe("fallback");
  });

  it("names the fields where something was taken out", () => {
    expect(cleanedNotice(["about_text", "footer_line"])).toBe(
      "Links, markup or hidden characters were removed from: About us, Footer line.",
    );
    expect(cleanedNotice([])).toBeNull();
    expect(cleanedNotice(["<script>"])).toBeNull();
    expect(cleanedNotice(["about_text", "<script>"])).toBe(
      "Links, markup or hidden characters were removed from: About us.",
    );
  });

  it("only administrators get the menu entry", () => {
    expect(canManageBranding({ permissions: ["branding:manage"] })).toBe(true);
    expect(canManageBranding({ permissions: ["lead:read:own"] })).toBe(false);
    const labels = (permissions: string[]) =>
      navigationFor({ permissions, user_type: "staff" }).map((i) => i.label);
    expect(labels(["branding:manage"])).toContain("Branding");
    expect(labels(["lead:read:own"])).not.toContain("Branding");
  });
});

describe("saveBranding", () => {
  it("sends the version, the normalised colour and the four texts only", async () => {
    apiFetch.mockResolvedValueOnce({ ...BRANDING, cleaned_fields: [] });
    await expect(
      saveBranding(3, initialFormState, form(FIELDS)),
    ).rejects.toThrow("REDIRECT:/branding?done=saved");
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe("/branding");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({
      version: 3,
      primary_color: "1f3a5f",
      about_text: "About",
      terms_text: "Terms",
      contact_line: "Contact",
      footer_line: "Footer",
    });
  });

  it("extra form fields are never forwarded", async () => {
    apiFetch.mockResolvedValueOnce({ ...BRANDING });
    await expect(
      saveBranding(
        0,
        initialFormState,
        form({ ...FIELDS, tenant_id: "x", version: "99" }),
      ),
    ).rejects.toThrow("REDIRECT");
    const body = JSON.parse(apiFetch.mock.calls[0][1].body);
    expect(body.tenant_id).toBeUndefined();
    expect(body.version).toBe(0);
  });

  it("tells the next page which fields were cleaned", async () => {
    apiFetch.mockResolvedValueOnce({
      ...BRANDING,
      cleaned_fields: ["about_text", "evil"],
    });
    await expect(
      saveBranding(3, initialFormState, form(FIELDS)),
    ).rejects.toThrow("REDIRECT:/branding?done=saved&cleaned=about_text");
  });

  it("a bad colour is refused before anything is sent and the text is kept", async () => {
    const result = await saveBranding(
      3,
      initialFormState,
      form({ ...FIELDS, primary_color: "red" }),
    );
    expect(apiFetch).not.toHaveBeenCalled();
    expect(result.fieldErrors.primary_color).toMatch(/six hex digits/);
    expect(result.values.about_text).toBe("About");
    expect(result.attempt).toBe(1);
  });

  it("a refusal from the API keeps what was typed and explains in words", async () => {
    apiFetch.mockRejectedValueOnce(problem(422, "branding_text_refused"));
    const result = await saveBranding(3, initialFormState, form(FIELDS));
    expect(result.values.terms_text).toBe("Terms");
    expect(result.error?.message).toMatch(/instructions/);
  });

  it("a version that is not a number is refused before anything is sent", async () => {
    apiFetch.mockResolvedValue({ ...BRANDING });
    await expect(
      saveBranding(-1, initialFormState, form(FIELDS)),
    ).rejects.toThrow("invalid version");
    await expect(
      saveBranding(1.5, initialFormState, form(FIELDS)),
    ).rejects.toThrow("invalid version");
    expect(apiFetch).not.toHaveBeenCalled();
  });
});

describe("uploadLogo and removeLogo", () => {
  const png = new File([new Uint8Array(100)], "logo.png", {
    type: "image/png",
  });

  it("sends only the file", async () => {
    apiFetch.mockResolvedValueOnce({});
    await expect(
      uploadLogo(
        initialFormState,
        (() => {
          const data = new FormData();
          data.set("file", png);
          data.set("tenant_id", "x");
          return data;
        })(),
      ),
    ).rejects.toThrow("REDIRECT:/branding?done=logo");
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe("/branding/logo");
    expect(init.method).toBe("PUT");
    expect([...init.body.keys()]).toEqual(["file"]);
  });

  it("a wrong type or no file is refused before anything is sent", async () => {
    const gif = new File([new Uint8Array(10)], "a.gif", { type: "image/gif" });
    const bad = new FormData();
    bad.set("file", gif);
    expect((await uploadLogo(initialFormState, bad)).fieldErrors.file).toMatch(
      /PNG or a JPEG/,
    );
    expect(
      (await uploadLogo(initialFormState, new FormData())).fieldErrors.file,
    ).toMatch(/Choose/);
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("the API's refusal is explained", async () => {
    apiFetch.mockRejectedValueOnce(problem(413, "logo_too_large"));
    const data = new FormData();
    data.set("file", png);
    expect((await uploadLogo(initialFormState, data)).error?.message).toMatch(
      /1 MB/,
    );
  });

  it("removing calls the delete endpoint and goes back", async () => {
    apiFetch.mockResolvedValueOnce({});
    await expect(removeLogo(initialFormState)).rejects.toThrow(
      "REDIRECT:/branding?done=logo-removed",
    );
    expect(apiFetch.mock.calls[0][0]).toBe("/branding/logo");
    expect(apiFetch.mock.calls[0][1].method).toBe("DELETE");
  });
});

describe("components", () => {
  it("the cover preview uses the colour and readable text, and shows the logo as an image", () => {
    render(
      <CoverPreview
        color="ffffff"
        logoSrc="data:image/png;base64,AAAA"
        name="Acme"
      />,
    );
    const box = screen.getByTestId("cover-preview");
    expect(box.style.backgroundColor).toBe("rgb(255, 255, 255)");
    expect(box.style.color).toBe("rgb(17, 17, 17)");
    expect(screen.getByAltText("Your logo")).toBeTruthy();
  });

  it("a colour that is not valid falls back to the default in the preview", () => {
    render(<CoverPreview color="not a colour" logoSrc={null} name="Acme" />);
    expect(screen.getByTestId("cover-preview").style.backgroundColor).toBe(
      "rgb(31, 58, 95)",
    );
    expect(screen.getByText("No logo yet")).toBeTruthy();
  });

  it("the form shows the saved values and previews a typed colour", async () => {
    render(
      <BrandingForm
        action={vi.fn()}
        branding={BRANDING}
        organisation="Acme"
        logoSrc={null}
      />,
    );
    expect(
      (screen.getByLabelText(/About us/) as HTMLTextAreaElement).value,
    ).toBe("We build homes.");
    const colour = screen.getByLabelText(/Brand colour/);
    await userEvent.clear(colour);
    await userEvent.type(colour, "ffffff");
    expect(screen.getByTestId("cover-preview").style.backgroundColor).toBe(
      "rgb(255, 255, 255)",
    );
  });

  it("texts are plain text fields, never markup", () => {
    render(
      <BrandingForm
        action={vi.fn()}
        branding={{ ...BRANDING, about_text: "<b>bold</b> <script>x</script>" }}
        organisation="Acme"
        logoSrc={null}
      />,
    );
    expect(
      (screen.getByLabelText(/About us/) as HTMLTextAreaElement).value,
    ).toContain("<b>bold</b>");
    expect(document.querySelector("b")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
  });

  it("a refusal keeps what was typed and shows the words", async () => {
    const action = vi.fn().mockResolvedValue({
      attempt: 1,
      values: { ...FIELDS, about_text: "my typed text" },
      fieldErrors: {},
      error: {
        code: "x",
        message: "Branding refused",
        fieldErrors: {},
        requestId: "r",
        status: 422,
      },
    });
    render(
      <BrandingForm
        action={action}
        branding={BRANDING}
        organisation="Acme"
        logoSrc={null}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Save branding" }),
    );
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Branding refused",
    );
    expect(
      (screen.getByLabelText(/About us/) as HTMLTextAreaElement).value,
    ).toBe("my typed text");
  });

  it("a refused logo shows the reason next to the field", async () => {
    const upload = vi.fn().mockResolvedValue({
      attempt: 1,
      values: {},
      fieldErrors: { file: "The logo must be a PNG or a JPEG." },
      error: null,
    });
    render(<LogoPanel upload={upload} remove={vi.fn()} hasLogo={false} />);
    await userEvent.upload(
      screen.getByLabelText(/Logo/),
      new File([new Uint8Array(10)], "a.png", { type: "image/png" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Upload logo" }));
    expect(
      await screen.findByText("The logo must be a PNG or a JPEG."),
    ).toBeTruthy();
  });

  it("the logo panel only offers PNG and JPEG and shows remove only when there is a logo", () => {
    const { rerender } = render(
      <LogoPanel upload={vi.fn()} remove={vi.fn()} hasLogo={false} />,
    );
    expect(screen.getByLabelText(/Logo/).getAttribute("accept")).toBe(
      "image/png,image/jpeg",
    );
    expect(screen.queryByRole("button", { name: "Remove logo" })).toBeNull();
    rerender(<LogoPanel upload={vi.fn()} remove={vi.fn()} hasLogo />);
    expect(screen.getByRole("button", { name: "Remove logo" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Replace logo" })).toBeTruthy();
  });
});

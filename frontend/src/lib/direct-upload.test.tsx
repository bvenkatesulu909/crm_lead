import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  finishDocumentUpload,
  startDocumentUpload,
} from "@/app/(app)/documents/actions";
import {
  finishKnowledgeUpload,
  startKnowledgeUpload,
} from "@/app/(app)/knowledge/actions";
import { UploadDocumentDialog } from "@/components/document-dialogs";
import { KnowledgeUploadForm } from "@/components/knowledge-form";
import { ApiError } from "@/lib/api-error";
import { initialDialogState } from "@/lib/dialog-state";
import {
  SEND_MESSAGES,
  directUpload,
  safeStoreUrl,
  sendToStore,
  storeForm,
  type UploadTicket,
} from "@/lib/direct-upload";
import { initialFormState } from "@/lib/form-state";
import nextConfig, { fileStoreOrigin } from "../../next.config";

/**
 * ADR 0025 step DU4: the browser sends files straight to the file store. The Server Actions
 * only ever see a file's name and size; the bytes go to the store's signed link.
 */

const apiFetch = vi.fn();
vi.mock("@/lib/server/api", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}));
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`REDIRECT:${to}`);
  },
  usePathname: () => "/accounts/1",
}));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));

const ACCOUNT = "11111111-1111-4111-8111-111111111111";
const UPLOAD = "22222222-2222-4222-8222-222222222222";

const ticket = (over: Partial<UploadTicket> = {}): UploadTicket => ({
  upload_id: UPLOAD,
  url: "https://store.example.test/crm-files",
  fields: {
    key: `pending/t/${UPLOAD}`,
    "Content-Type": "application/pdf",
    policy: "p",
  },
  expires_at: "2026-11-10T10:05:00Z",
  max_bytes: 100,
  ...over,
});

/** A stand-in for XMLHttpRequest: records what was sent and answers as told. */
class FakeXhr {
  static last: FakeXhr | null = null;
  static answer: { status?: number; error?: boolean; timeout?: boolean } = {
    status: 204,
  };
  method = "";
  url = "";
  body: FormData | null = null;
  status = 0;
  timeout = 0;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  upload: { onprogress: ((e: ProgressEvent) => void) | null } = {
    onprogress: null,
  };
  constructor() {
    FakeXhr.last = this;
  }
  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }
  abort() {}
  send(body: FormData) {
    this.body = body;
    const a = FakeXhr.answer;
    this.upload.onprogress?.({
      lengthComputable: true,
      loaded: 50,
      total: 100,
    } as ProgressEvent);
    queueMicrotask(() => {
      if (a.error) return this.onerror?.();
      if (a.timeout) return this.ontimeout?.();
      this.status = a.status ?? 204;
      this.onload?.();
    });
  }
}

const fake = () => new FakeXhr() as unknown as XMLHttpRequest;
const pdf = (size = 10) =>
  new File([new Uint8Array(size)], "terms.pdf", { type: "application/pdf" });

function problem(status: number, code: string, detail = "Server words") {
  return new ApiError(status, {
    title: "x",
    status,
    detail,
    code,
    request_id: "req-1",
  });
}

afterEach(() => {
  FakeXhr.answer = { status: 204 };
  FakeXhr.last = null;
  apiFetch.mockReset();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("sendToStore", () => {
  it("posts the signed fields first and the file last, to the ticket's address", async () => {
    const progress: number[] = [];
    const result = await sendToStore(
      ticket(),
      pdf(),
      (p) => progress.push(p),
      fake,
    );
    expect(result).toBe("sent");
    const xhr = FakeXhr.last!;
    expect([xhr.method, xhr.url]).toEqual([
      "POST",
      "https://store.example.test/crm-files",
    ]);
    const keys = [...xhr.body!.keys()];
    expect(keys).toEqual(["key", "Content-Type", "policy", "file"]);
    expect(progress).toEqual([50, 100]);
  });

  it.each([
    [{ status: 403 }, "refused"],
    [{ status: 400 }, "refused"],
    [{ status: 307 }, "refused"], // how SeaweedFS refuses a tampered upload
    [{ status: 0 }, "unreachable"], // blocked by CORS or offline
    [{ error: true }, "unreachable"],
    [{ timeout: true }, "unreachable"],
  ])("answer %j means %s", async (answer, expected) => {
    FakeXhr.answer = answer;
    expect(await sendToStore(ticket(), pdf(), () => {}, fake)).toBe(expected);
  });

  it.each([
    "javascript:alert(1)",
    "data:text/html,x",
    "/relative/path",
    "not a url",
  ])("never follows %s", async (url) => {
    expect(await sendToStore(ticket({ url }), pdf(), () => {}, fake)).toBe(
      "bad_ticket",
    );
    expect(FakeXhr.last).toBeNull();
  });

  it("does not send a file bigger than the ticket allows", async () => {
    expect(
      await sendToStore(ticket({ max_bytes: 5 }), pdf(10), () => {}, fake),
    ).toBe("too_large");
    expect(FakeXhr.last).toBeNull();
  });

  it("knows only http(s) addresses", () => {
    expect(safeStoreUrl("https://storage.googleapis.com/b")).toBe(
      "https://storage.googleapis.com/b",
    );
    expect(safeStoreUrl("ftp://x")).toBeNull();
    expect([...storeForm(ticket({ fields: {} }), pdf()).keys()]).toEqual([
      "file",
    ]);
  });
});

describe("directUpload", () => {
  it("does not send anything when the API refuses to start", async () => {
    const send = vi.fn();
    const finish = vi.fn();
    const out = await directUpload(
      pdf(),
      async () => ({ fieldErrors: { file: "no" }, error: null }),
      finish,
      () => {},
      send,
    );
    expect(out).toEqual({
      ok: false,
      fieldErrors: { file: "no" },
      error: null,
    });
    expect(send).not.toHaveBeenCalled();
    expect(finish).not.toHaveBeenCalled();
  });

  it("does not finish when the store did not take the file", async () => {
    const finish = vi.fn();
    const out = await directUpload(
      pdf(),
      async () => ({ ticket: ticket() }),
      finish,
      () => {},
      async () => "refused",
    );
    expect(out.ok).toBe(false);
    expect(!out.ok && out.error?.message).toBe(SEND_MESSAGES.refused);
    expect(finish).not.toHaveBeenCalled();
  });

  it("finishes with the ticket's upload id once the file is in the store", async () => {
    const finish = vi.fn(async (id: string) => id);
    const out = await directUpload(
      pdf(),
      async () => ({ ticket: ticket() }),
      finish,
      () => {},
      async () => "sent",
    );
    expect(out).toEqual({ ok: true, result: UPLOAD });
  });
});

describe("document upload Server Actions", () => {
  it("send only the name and the size to the API - never the bytes", async () => {
    apiFetch.mockResolvedValue(ticket());
    const result = await startDocumentUpload("account", ACCOUNT, {
      fileName: "terms.pdf",
      size: 15 * 1024 * 1024,
      description: "  Terms  ",
      customerVisible: true,
    });
    expect(result).toEqual({ ticket: ticket() });
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe("/documents/uploads");
    expect(JSON.parse(init.body as string)).toEqual({
      record_type: "account",
      record_id: ACCOUNT,
      file_name: "terms.pdf",
      size_bytes: 15 * 1024 * 1024,
      customer_visible: true,
      description: "Terms",
    });
  });

  it("never shares a deal's document with the customer", async () => {
    apiFetch.mockResolvedValue(ticket());
    await startDocumentUpload("opportunity", ACCOUNT, {
      fileName: "a.pdf",
      size: 3,
      description: "",
      customerVisible: true,
    });
    expect(
      JSON.parse(apiFetch.mock.calls[0][1].body as string).customer_visible,
    ).toBe(false);
  });

  it.each([
    [{ fileName: "", size: 3 }, "file"],
    [{ fileName: "a.pdf", size: 0 }, "file"],
    [{ fileName: "a.pdf", size: 20 * 1024 * 1024 + 1 }, "file"],
    [
      { fileName: "a.pdf", size: 3, description: "x".repeat(501) },
      "description",
    ],
  ])("refuses %j before asking the API", async (info, field) => {
    const result = await startDocumentUpload("account", ACCOUNT, {
      description: "",
      customerVisible: false,
      ...info,
    });
    expect("fieldErrors" in result && result.fieldErrors[field]).toBeTruthy();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("shows the API's reason when it refuses", async () => {
    apiFetch.mockRejectedValue(
      problem(415, "file_type_not_allowed", "This file type isn't allowed."),
    );
    const result = await startDocumentUpload("account", ACCOUNT, {
      fileName: "tool.exe",
      size: 4,
      description: "",
      customerVisible: false,
    });
    expect("error" in result && result.error?.message).toBe(
      "This file type isn't allowed.",
    );
  });

  it("refuses a made-up record or upload id", async () => {
    await expect(
      startDocumentUpload("account", "../x", {
        fileName: "a.pdf",
        size: 1,
        description: "",
        customerVisible: false,
      }),
    ).rejects.toThrow();
    await expect(
      finishDocumentUpload("account", ACCOUNT, "x/../y", initialDialogState),
    ).rejects.toThrow();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("finish goes back to the record; a refusal keeps the dialog open with the reason", async () => {
    apiFetch.mockResolvedValue({});
    await expect(
      finishDocumentUpload("account", ACCOUNT, UPLOAD, initialDialogState),
    ).rejects.toThrow(`REDIRECT:/accounts/${ACCOUNT}?done=document-uploaded`);
    expect(apiFetch).toHaveBeenCalledWith(
      `/documents/uploads/${UPLOAD}/finish`,
      { method: "POST" },
    );
    apiFetch.mockRejectedValue(
      problem(409, "upload_not_received", "Not arrived yet."),
    );
    const state = await finishDocumentUpload(
      "account",
      ACCOUNT,
      UPLOAD,
      initialDialogState,
    );
    expect([state.attempt, state.error?.message]).toEqual([
      1,
      "Not arrived yet.",
    ]);
  });
});

describe("knowledge upload Server Actions", () => {
  it("send only the name, size, title and visibility", async () => {
    apiFetch.mockResolvedValue(ticket());
    await startKnowledgeUpload({
      fileName: "faq.md",
      size: 9,
      title: " FAQ ",
      visibility: "customer_visible",
    });
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe("/knowledge/uploads");
    expect(JSON.parse(init.body as string)).toEqual({
      file_name: "faq.md",
      size_bytes: 9,
      visibility: "customer_visible",
      title: "FAQ",
    });
  });

  it("refuses an unknown visibility before asking the API", async () => {
    const result = await startKnowledgeUpload({
      fileName: "a.md",
      size: 1,
      title: "",
      visibility: "public",
    });
    expect(
      "fieldErrors" in result && result.fieldErrors.visibility,
    ).toBeTruthy();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("finish goes to the knowledge list", async () => {
    apiFetch.mockResolvedValue({});
    await expect(
      finishKnowledgeUpload(UPLOAD, initialFormState),
    ).rejects.toThrow("REDIRECT:/knowledge?done=uploaded");
  });
});

describe("the upload screens", () => {
  it("the document dialog sends the file to the store, never to the Server Action", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
    const start = vi.fn(async () => ({ ticket: ticket({ max_bytes: 1000 }) }));
    const finish = vi.fn(async () => ({
      attempt: 1,
      fieldErrors: {},
      error: null,
    }));
    render(
      <UploadDocumentDialog
        start={start}
        finish={finish}
        allowCustomerVisible
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Upload" }));
    await user.upload(screen.getByLabelText("File"), pdf(20));
    await user.click(
      screen.getByLabelText("Visible to the customer in the portal"),
    );
    await user.click(screen.getAllByRole("button", { name: "Upload" })[1]);
    await waitFor(() =>
      expect(finish).toHaveBeenCalledWith(UPLOAD, expect.anything()),
    );
    expect(start).toHaveBeenCalledWith({
      fileName: "terms.pdf",
      size: 20,
      description: "",
      customerVisible: true,
    });
    expect(FakeXhr.last!.body!.get("file")).toBeInstanceOf(File);
  });

  it("the document dialog explains a store that cannot be reached", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
    FakeXhr.answer = { error: true };
    const finish = vi.fn();
    render(
      <UploadDocumentDialog
        start={async () => ({ ticket: ticket({ max_bytes: 1000 }) })}
        finish={finish}
        allowCustomerVisible={false}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Upload" }));
    await user.upload(screen.getByLabelText("File"), pdf(20));
    await user.click(screen.getAllByRole("button", { name: "Upload" })[1]);
    expect(
      await screen.findByText(SEND_MESSAGES.unreachable),
    ).toBeInTheDocument();
    expect(finish).not.toHaveBeenCalled();
  });

  it("the knowledge form shows the API's refusal and keeps what was typed", async () => {
    const start = vi.fn(async () => ({
      values: { title: "Big", visibility: "internal" },
      fieldErrors: { file: "The file is larger than 20 MB." },
      error: null,
    }));
    render(<KnowledgeUploadForm start={start} finish={vi.fn()} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/Title/), "Big");
    // jsdom's form validation cannot see a file set by a test, so `required` would block the
    // submit here (real browsers see it); the server-side checks are what this test is about.
    screen.getByLabelText("File").removeAttribute("required");
    await user.upload(
      screen.getByLabelText("File"),
      new File(["# hi"], "faq.md"),
    );
    await user.click(
      screen.getByRole("button", { name: "Upload for indexing" }),
    );
    expect(
      await screen.findByText("The file is larger than 20 MB."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/Title/)).toHaveValue("Big");
    expect(start).toHaveBeenCalledWith({
      fileName: "faq.md",
      size: 4,
      title: "Big",
      visibility: "internal",
    });
  });
});

describe("the content security policy lists the file store (ADR 0025)", () => {
  it("accepts only an http(s) origin", () => {
    expect(fileStoreOrigin("https://storage.googleapis.com/some/path")).toBe(
      "https://storage.googleapis.com",
    );
    expect(fileStoreOrigin("http://127.0.0.1:9400")).toBe(
      "http://127.0.0.1:9400",
    );
    expect(fileStoreOrigin("javascript:alert(1)")).toBeNull();
    expect(fileStoreOrigin("")).toBeNull();
    expect(fileStoreOrigin(undefined)).toBeNull();
  });

  it("adds connect-src only when FILE_STORE_ORIGIN is set", async () => {
    const policy = async () => {
      vi.resetModules();
      const config = (await import("../../next.config")).default;
      const headers = (await config.headers!()).flatMap((r) => r.headers);
      return headers.find(
        (h) => h.key === "Content-Security-Policy-Report-Only",
      )!.value;
    };
    vi.stubEnv("FILE_STORE_ORIGIN", "https://storage.googleapis.com/");
    expect(await policy()).toContain(
      "connect-src 'self' https://storage.googleapis.com",
    );
    vi.stubEnv("FILE_STORE_ORIGIN", "");
    expect(await policy()).not.toContain("connect-src");
  });

  it("the web app no longer accepts large Server Action bodies", () => {
    expect(
      nextConfig.experimental?.serverActions?.bodySizeLimit,
    ).toBeUndefined();
  });
});

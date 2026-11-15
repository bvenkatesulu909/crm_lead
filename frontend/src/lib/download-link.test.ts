// Downloads by signed link (ADR 0025, step DU3a): the route handlers send the browser straight to
// the file store, so large files never pass through this host. Only an absolute http(s) address
// may be followed, and problems go back to the page with a message, as before.
import { describe, expect, it, vi } from "vitest";

vi.mock("next/headers", () => ({ cookies: vi.fn() }));

import { safeDownloadUrl } from "@/lib/server/api";
import { linkResponse } from "@/lib/server/file-response";

const BACK = "https://crm.example.test/accounts/1";

describe("which link may be followed", () => {
  it("keeps an absolute https or http address", () => {
    expect(
      safeDownloadUrl("https://storage.googleapis.com/b/k?X-Goog-Signature=a"),
    ).toBe("https://storage.googleapis.com/b/k?X-Goog-Signature=a");
    expect(safeDownloadUrl("http://127.0.0.1:9400/crm-files/k")).toBe(
      "http://127.0.0.1:9400/crm-files/k",
    );
  });

  it.each([
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "/relative/path",
    "//evil.example/x",
    "file:///etc/passwd",
    "",
    42,
    null,
    undefined,
  ])("refuses %s", (value) => {
    expect(safeDownloadUrl(value)).toBeNull();
  });
});

describe("the response a download route sends", () => {
  it("redirects to the link, uncached and without telling the store where it came from", () => {
    const response = linkResponse(
      { ok: true, url: "https://store.example.test/f?sig=1" },
      new URL(BACK),
    );
    expect(response.status).toBe(302);
    expect(response.headers.get("location")).toBe(
      "https://store.example.test/f?sig=1",
    );
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(response.headers.get("referrer-policy")).toBe("no-referrer");
  });

  it.each([
    [404, "missing"],
    [403, "missing"],
    [409, "not-sent"],
    [503, "unavailable"],
    [500, "unavailable"],
  ])("a %i goes back to the page with ?file=%s", (status, reason) => {
    const response = linkResponse({ ok: false, status }, new URL(BACK));
    expect(response.headers.get("location")).toBe(`${BACK}?file=${reason}`);
  });

  it("an expired sign-in goes to the login page", () => {
    const response = linkResponse({ ok: false, status: 401 }, new URL(BACK));
    expect(response.headers.get("location")).toBe(
      "https://crm.example.test/login",
    );
  });
});

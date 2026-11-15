import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createClip,
  deleteClip,
  editClip,
  listenToClip,
  readClips,
} from "@/app/(app)/leads/[id]/call-actions";
import {
  CLIP_REFRESH_MS,
  ClipsPanel,
  type ClipsActions,
} from "@/components/calls-clips";
import { ApiError } from "@/lib/api-error";
import {
  checkNewClip,
  clipErrorText,
  clipRange,
  clipStatusLabel,
  parseClock,
  type CallClip,
  type CallDetail,
} from "@/lib/calls";

const apiFetch = vi.fn();
vi.mock("@/lib/server/api", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}));
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`REDIRECT:${to}`);
  },
  useRouter: () => ({ refresh: vi.fn() }),
}));

function problem(status: number, code: string) {
  return new ApiError(status, {
    title: "x",
    status,
    detail: "Server words",
    code,
    request_id: "r",
  });
}

const LEAD = "11111111-1111-4111-8111-111111111111";
const CALL = "22222222-2222-4222-8222-222222222222";
const CLIP = "33333333-3333-4333-8333-333333333333";

function clip(changes: Partial<CallClip> = {}): CallClip {
  return {
    id: CLIP,
    recording_id: CALL,
    lead_id: LEAD,
    made_by_user_id: "44444444-4444-4444-8444-444444444444",
    start_ms: 2000,
    end_ms: 9000,
    duration_ms: 7000,
    title: "Budget stated",
    note: null,
    excerpt: "[0:02] My budget is one point two crore.",
    status: "ready",
    failure_code: null,
    created_at: "2026-11-15T09:00:00Z",
    audio_available: true,
    audio_deleted_at: null,
    ...changes,
  };
}

const DETAIL: CallDetail = {
  id: CALL,
  lead_id: LEAD,
  language: "en",
  status: "ready",
  failure_code: null,
  file_name: "call.mp3",
  size_bytes: 2000,
  duration_seconds: 90,
  consent_confirmed_at: "2026-11-15T08:00:00Z",
  created_at: "2026-11-15T08:00:00Z",
  finished_at: "2026-11-15T08:01:00Z",
  audio_available: true,
  audio_deleted_at: null,
  has_transcript: true,
  engine: "fake",
  transcript: "Hello. My budget is one point two crore.",
  segments: [
    { start: 0, end: 3, text: "Hello." },
    { start: 3, end: 6.5, text: "My budget is one point two crore." },
  ],
};

beforeEach(() => apiFetch.mockReset());

describe("parseClock", () => {
  it("reads m:ss, h:mm:ss and plain seconds", () => {
    expect(parseClock("1:05")).toBe(65);
    expect(parseClock("0:03")).toBe(3);
    expect(parseClock("1:02:05")).toBe(3725);
    expect(parseClock(" 75 ")).toBe(75);
    expect(parseClock("0")).toBe(0);
  });

  it("refuses anything else", () => {
    for (const bad of [
      "",
      " ",
      "abc",
      "1:5",
      "1:60",
      "-1",
      "1.5",
      "1:2:3:4",
      "99:99:99",
      "1;2",
      "1:60:00",
      "1:75:00",
      "1:30:60",
    ])
      expect(parseClock(bad)).toBeNull();
  });
});

describe("checkNewClip", () => {
  const ok = {
    start: "0:02",
    end: "0:09",
    title: " Budget ",
    note: "",
    duration: 90,
  };

  it("builds the request from whole milliseconds and trimmed texts", () => {
    expect(checkNewClip(ok)).toEqual({
      ok: true,
      body: { start_ms: 2000, end_ms: 9000, title: "Budget", note: null },
    });
    const noted = checkNewClip({ ...ok, note: " ask about the loan " });
    expect(noted.ok && noted.body.note).toBe("ask about the loan");
  });

  it("explains each mistake next to its field", () => {
    const cases: [Partial<typeof ok>, string][] = [
      [{ start: "" }, "start"],
      [{ end: "x" }, "end"],
      [{ end: "0:02" }, "end"],
      [{ end: "0:03" }, "end"],
      [{ end: "2:03" }, "end"],
      [{ end: "1:31" }, "end"],
      [{ title: "   " }, "title"],
      [{ title: "a".repeat(101) }, "title"],
      [{ note: "a".repeat(501) }, "note"],
    ];
    for (const [change, field] of cases) {
      const result = checkNewClip({ ...ok, ...change });
      expect(result.ok).toBe(false);
      if (!result.ok) expect(Object.keys(result.fieldErrors)).toContain(field);
    }
  });

  it("refuses a moment longer than 2 minutes even inside a long recording", () => {
    const long = { ...ok, duration: 600 };
    for (const [start, end] of [
      ["0:02", "2:03"],
      ["0:00", "2:01"],
      ["1:00", "3:30"],
    ]) {
      const result = checkNewClip({ ...long, start, end });
      expect(result.ok).toBe(false);
      if (!result.ok)
        expect(result.fieldErrors.end).toMatch(/at most 2 minutes/);
    }
  });

  it("accepts exactly 3 seconds, 120 seconds and the end of the recording", () => {
    expect(checkNewClip({ ...ok, start: "0:00", end: "0:03" }).ok).toBe(true);
    expect(
      checkNewClip({ ...ok, start: "0:00", end: "2:00", duration: 600 }).ok,
    ).toBe(true);
    expect(
      checkNewClip({ ...ok, start: "1:00", end: "1:30", duration: 90 }).ok,
    ).toBe(true);
  });

  it("refuses a recording whose length is not known", () => {
    expect(checkNewClip({ ...ok, duration: null }).ok).toBe(false);
  });
});

describe("words", () => {
  it("shows a range as start-end", () => {
    expect(clipRange(clip())).toBe("0:02–0:09");
    expect(clipRange(clip({ start_ms: 65_000, end_ms: 125_000 }))).toBe(
      "1:05–2:05",
    );
  });

  it("has a plain label per status", () => {
    expect(clipStatusLabel(clip({ status: "queued" }))).toMatch(/being cut/i);
    expect(clipStatusLabel(clip())).toBe("Ready");
    expect(clipStatusLabel(clip({ status: "failed" }))).toMatch(/could not/i);
    expect(
      clipStatusLabel(clip({ audio_deleted_at: "2026-11-16T00:00:00Z" })),
    ).toMatch(/audio was deleted/i);
  });

  it("explains the known refusals", () => {
    expect(clipErrorText("clip_invalid", "x")).toBe("x");
    expect(clipErrorText("clip_limit_reached", "x")).toMatch(
      /at most 20 clips/,
    );
    expect(clipErrorText("call_audio_deleted", "x")).toMatch(/audio/);
    expect(clipErrorText("call_not_ready", "x")).toMatch(/not ready/);
    expect(clipErrorText("clip_not_found", "x")).toMatch(/not found/);
    expect(clipErrorText("forbidden", "x")).toMatch(/maker|manager/i);
    expect(clipErrorText("other", "fallback")).toBe("fallback");
  });
});

describe("clip Server Actions", () => {
  it("read the clips of a recording", async () => {
    apiFetch.mockResolvedValueOnce({ items: [clip()] });
    const result = await readClips(LEAD, CALL);
    expect(result).toEqual({ ok: true, value: [clip()] });
    expect(apiFetch.mock.calls[0][0]).toBe(
      `/leads/${LEAD}/calls/${CALL}/clips`,
    );
  });

  it("send only the moment and the texts when making one", async () => {
    apiFetch.mockResolvedValueOnce(clip());
    const result = await createClip(LEAD, CALL, {
      start: "0:02",
      end: "0:09",
      title: " Budget ",
      note: "",
      duration: 90,
      tenant_id: "x",
      status: "ready",
    } as never);
    expect(result.ok).toBe(true);
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe(`/leads/${LEAD}/calls/${CALL}/clips`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      start_ms: 2000,
      end_ms: 9000,
      title: "Budget",
      note: null,
    });
  });

  it("refuse a bad moment before anything is sent", async () => {
    const result = await createClip(LEAD, CALL, {
      start: "0:09",
      end: "0:02",
      title: "t",
      note: "",
      duration: 90,
    });
    expect(result.ok).toBe(false);
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("change only the title and the note", async () => {
    apiFetch.mockResolvedValueOnce(clip({ title: "New" }));
    await editClip(LEAD, CALL, CLIP, { title: " New ", note: "" });
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe(`/leads/${LEAD}/calls/${CALL}/clips/${CLIP}`);
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({ title: "New", note: null });
  });

  it("delete a clip", async () => {
    apiFetch.mockResolvedValueOnce(undefined);
    expect(await deleteClip(LEAD, CALL, CLIP)).toEqual({
      ok: true,
      value: null,
    });
    expect(apiFetch.mock.calls[0][1]).toEqual({ method: "DELETE" });
  });

  it("ask for a short link to listen and keep only a web address", async () => {
    apiFetch.mockResolvedValueOnce({
      url: "https://files.example/clip.mp3",
      expires_in_seconds: 60,
      which: "cleaned",
    });
    const heard = await listenToClip(LEAD, CALL, CLIP);
    expect(heard.ok && heard.value.url).toBe("https://files.example/clip.mp3");
    apiFetch.mockResolvedValueOnce({
      url: "javascript:alert(1)",
      expires_in_seconds: 60,
      which: "cleaned",
    });
    expect((await listenToClip(LEAD, CALL, CLIP)).ok).toBe(false);
  });

  it("refuse ids that are not ids before anything is sent", async () => {
    await expect(readClips("../x", CALL)).rejects.toThrow();
    await expect(readClips(LEAD, "../x")).rejects.toThrow();
    await expect(deleteClip(LEAD, CALL, "../x")).rejects.toThrow();
    await expect(listenToClip(LEAD, CALL, "../x")).rejects.toThrow();
    await expect(
      editClip(LEAD, CALL, "../x", { title: "t", note: "" }),
    ).rejects.toThrow();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("turn a refusal into plain words", async () => {
    apiFetch.mockRejectedValueOnce(problem(429, "clip_limit_reached"));
    const result = await createClip(LEAD, CALL, {
      start: "0:02",
      end: "0:09",
      title: "t",
      note: "",
      duration: 90,
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.message).toMatch(/at most 20 clips/);
  });
});

describe("ClipsPanel", () => {
  const actions = (over: Partial<ClipsActions> = {}): ClipsActions => ({
    list: vi.fn().mockResolvedValue({ ok: true, value: [clip()] }),
    create: vi.fn().mockResolvedValue({ ok: true, value: clip() }),
    edit: vi
      .fn()
      .mockResolvedValue({ ok: true, value: clip({ title: "New" }) }),
    remove: vi.fn().mockResolvedValue({ ok: true, value: null }),
    listen: vi.fn().mockResolvedValue({
      ok: true,
      value: {
        url: "https://files.example/c.mp3",
        expires_in_seconds: 60,
        which: "cleaned",
      },
    }),
    ...over,
  });

  function show(a: ClipsActions, canWrite = true, detail: CallDetail = DETAIL) {
    return render(<ClipsPanel call={detail} canWrite={canWrite} actions={a} />);
  }

  it("lists the clips with their range, status and lines as plain text", async () => {
    show(actions());
    const item = await screen.findByTestId("clip-item");
    expect(within(item).getByText("Budget stated")).toBeTruthy();
    expect(within(item).getByText("0:02–0:09")).toBeTruthy();
    expect(within(item).getByTestId("clip-excerpt").textContent).toBe(
      "[0:02] My budget is one point two crore.",
    );
  });

  it("shows markup in a title or note as typed, never as HTML", async () => {
    const dirty = clip({
      title: "<b>Hi</b>",
      note: "<img src=x onerror=alert(1)>",
    });
    show(
      actions({
        list: vi.fn().mockResolvedValue({ ok: true, value: [dirty] }),
      }),
    );
    await screen.findByTestId("clip-item");
    expect(screen.getByText("<b>Hi</b>")).toBeTruthy();
    expect(document.querySelector("img")).toBeNull();
  });

  it("says so when there are no clips yet", async () => {
    show(actions({ list: vi.fn().mockResolvedValue({ ok: true, value: [] }) }));
    expect(await screen.findByText(/No clips yet/)).toBeTruthy();
  });

  it("shows the reason when the clips cannot be read", async () => {
    show(
      actions({
        list: vi.fn().mockResolvedValue({ ok: false, message: "Not allowed." }),
      }),
    );
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Not allowed.",
    );
  });

  it("makes a clip from the typed moment and clears the form", async () => {
    const a = actions();
    show(a);
    await screen.findByTestId("clip-item");
    await userEvent.type(screen.getByLabelText("Start (m:ss)"), "0:03");
    await userEvent.type(screen.getByLabelText("End (m:ss)"), "0:08");
    await userEvent.type(screen.getByLabelText("Title"), "Loan worry");
    await userEvent.click(screen.getByRole("button", { name: "Make clip" }));
    await waitFor(() => expect(a.create).toHaveBeenCalledTimes(1));
    expect(a.create).toHaveBeenCalledWith({
      start: "0:03",
      end: "0:08",
      title: "Loan worry",
      note: "",
      duration: 90,
    });
    await waitFor(() =>
      expect((screen.getByLabelText("Title") as HTMLInputElement).value).toBe(
        "",
      ),
    );
  });

  it("keeps what was typed and explains a refusal", async () => {
    const a = actions({
      create: vi.fn().mockResolvedValue({
        ok: false,
        message: "A recording can have at most 20 clips.",
      }),
    });
    show(a);
    await screen.findByTestId("clip-item");
    await userEvent.type(screen.getByLabelText("Start (m:ss)"), "0:03");
    await userEvent.type(screen.getByLabelText("End (m:ss)"), "0:08");
    await userEvent.type(screen.getByLabelText("Title"), "Loan worry");
    await userEvent.click(screen.getByRole("button", { name: "Make clip" }));
    expect((await screen.findByRole("alert")).textContent).toContain(
      "at most 20 clips",
    );
    expect((screen.getByLabelText("Title") as HTMLInputElement).value).toBe(
      "Loan worry",
    );
    expect(
      (screen.getByLabelText("Start (m:ss)") as HTMLInputElement).value,
    ).toBe("0:03");
    expect(
      (screen.getByLabelText("End (m:ss)") as HTMLInputElement).value,
    ).toBe("0:08");
  });

  it("checks the moment before asking the server", async () => {
    const a = actions();
    show(a);
    await screen.findByTestId("clip-item");
    await userEvent.type(screen.getByLabelText("Start (m:ss)"), "0:09");
    await userEvent.type(screen.getByLabelText("End (m:ss)"), "0:04");
    await userEvent.type(screen.getByLabelText("Title"), "t");
    await userEvent.click(screen.getByRole("button", { name: "Make clip" }));
    expect(a.create).not.toHaveBeenCalled();
    expect(
      screen.getByText(/at least 3 seconds|after the start/i),
    ).toBeTruthy();
  });

  it("people who can only read see the clips and can listen, but cannot make, edit or delete", async () => {
    show(actions(), false);
    await screen.findByTestId("clip-item");
    expect(screen.queryByLabelText("Title")).toBeNull();
    expect(screen.queryByRole("button", { name: "Make clip" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    expect(screen.getByRole("button", { name: "Listen" })).toBeTruthy();
  });

  it("listens through a short link in a player", async () => {
    const a = actions();
    show(a);
    await screen.findByTestId("clip-item");
    await userEvent.click(screen.getByRole("button", { name: "Listen" }));
    await waitFor(() => expect(a.listen).toHaveBeenCalledWith(CLIP));
    await waitFor(() =>
      expect(document.querySelector("audio")?.getAttribute("src")).toBe(
        "https://files.example/c.mp3",
      ),
    );
  });

  it("has no Listen button while the clip is being cut or after its audio was deleted", async () => {
    show(
      actions({
        list: vi.fn().mockResolvedValue({
          ok: true,
          value: [
            clip({ status: "queued", audio_available: false }),
            clip({
              id: "55555555-5555-4555-8555-555555555555",
              audio_deleted_at: "2026-11-16T00:00:00Z",
              audio_available: false,
            }),
          ],
        }),
      }),
    );
    await screen.findAllByTestId("clip-item");
    expect(screen.queryByRole("button", { name: "Listen" })).toBeNull();
  });

  it("edits the title and the note", async () => {
    const a = actions();
    show(a);
    await screen.findByTestId("clip-item");
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    const title = screen.getByLabelText("Clip title");
    await userEvent.clear(title);
    await userEvent.type(title, "New");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(a.edit).toHaveBeenCalledWith(CLIP, { title: "New", note: "" }),
    );
  });

  it("asks before deleting and only then deletes", async () => {
    const a = actions();
    show(a);
    await screen.findByTestId("clip-item");
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(a.remove).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(a.remove).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await userEvent.click(screen.getByRole("button", { name: "Yes, delete" }));
    await waitFor(() => expect(a.remove).toHaveBeenCalledWith(CLIP));
  });

  it("a transcript line can fill the start or the end of the moment", async () => {
    show(actions());
    await screen.findByTestId("clip-item");
    const lines = screen.getAllByTestId("clip-pick-line");
    await userEvent.click(
      within(lines[1]).getByRole("button", { name: "Start here" }),
    );
    await userEvent.click(
      within(lines[1]).getByRole("button", { name: "End here" }),
    );
    expect(
      (screen.getByLabelText("Start (m:ss)") as HTMLInputElement).value,
    ).toBe("0:03");
    expect(
      (screen.getByLabelText("End (m:ss)") as HTMLInputElement).value,
    ).toBe("0:06");
  });

  describe("while a clip is being cut", () => {
    beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
    afterEach(() => vi.useRealTimers());

    it("looks again every few seconds, and stops once nothing is waiting", async () => {
      const list = vi
        .fn()
        .mockResolvedValueOnce({
          ok: true,
          value: [clip({ status: "queued", audio_available: false })],
        })
        .mockResolvedValue({ ok: true, value: [clip()] });
      show(actions({ list }));
      await screen.findByTestId("clip-item");
      expect(list).toHaveBeenCalledTimes(1);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(CLIP_REFRESH_MS);
      });
      expect(list).toHaveBeenCalledTimes(2);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(CLIP_REFRESH_MS * 3);
      });
      expect(list).toHaveBeenCalledTimes(2); // nothing waiting any more
    });
  });
});

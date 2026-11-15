import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  deleteCallAudio,
  finishCallUpload,
  listenToCall,
  readCallTranscript,
  startCallUpload,
} from "@/app/(app)/leads/[id]/call-actions";
import {
  CallsView,
  REFRESH_MS,
  TranscriptPanel,
  type CallsActions,
} from "@/components/calls-views";
import { ApiError } from "@/lib/api-error";
import {
  callErrorText,
  callsPath,
  checkNewCall,
  failureText,
  formatDuration,
  formatSize,
  isWorking,
  languageLabel,
  safeAudioUrl,
  statusLabel,
  type CallDetail,
  type CallRecording,
} from "@/lib/calls";
import { initialDialogState } from "@/lib/dialog-state";
import { canReadCalls, canWriteCalls } from "@/lib/permissions";

const apiFetch = vi.fn();
vi.mock("@/lib/server/api", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}));
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`REDIRECT:${to}`);
  },
  useRouter: () => ({ refresh }),
}));
const refresh = vi.fn();

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

function call(changes: Partial<CallRecording> = {}): CallRecording {
  return {
    id: CALL,
    lead_id: LEAD,
    language: "hi",
    status: "ready",
    failure_code: null,
    file_name: "call 12 nov.mp3",
    size_bytes: 3 * 1024 * 1024,
    duration_seconds: 125,
    consent_confirmed_at: "2026-11-13T10:00:00Z",
    created_at: "2026-11-13T10:00:00Z",
    finished_at: "2026-11-13T10:01:00Z",
    audio_available: true,
    audio_deleted_at: null,
    has_transcript: true,
    engine: "openai:whisper-1",
    ...changes,
  };
}

function detail(changes: Partial<CallDetail> = {}): CallDetail {
  return {
    ...call(),
    transcript: "Namaste. Nenu flat kavali.",
    segments: [
      { start: 0, end: 2.5, text: "Namaste." },
      { start: 65, end: 70, text: "Nenu flat kavali." },
    ],
    ...changes,
  };
}

// --- the words and the checks ----------------------------------------------------------------

describe("call helpers", () => {
  it("names every status in words", () => {
    expect(statusLabel({ status: "queued" })).toMatch(
      /cleaned and transcribed/,
    );
    expect(statusLabel({ status: "processing" })).toMatch(
      /cleaned and transcribed/,
    );
    expect(statusLabel({ status: "ready" })).toBe("Transcript ready");
    expect(statusLabel({ status: "failed" })).toBe("Could not be processed");
    expect(statusLabel({ status: "expired" })).toBe("Upload expired");
    expect(statusLabel({ status: "uploading" })).toBe("Upload not finished");
    expect(statusLabel({ status: "x" })).toBe("Unknown");
  });

  it("knows which recordings the worker still has", () => {
    expect(isWorking({ status: "queued" })).toBe(true);
    expect(isWorking({ status: "processing" })).toBe(true);
    expect(isWorking({ status: "ready" })).toBe(false);
    expect(isWorking({ status: "failed" })).toBe(false);
  });

  it("explains each failure code and has a fallback", () => {
    for (const code of [
      "too_long",
      "unreadable",
      "no_speech",
      "call_audio_off",
      "budget_reached",
      "audio_deleted",
      "processing_failed",
    ])
      expect(failureText(code)).not.toBe(failureText(null));
    expect(failureText("something_new")).toBe(
      "The recording could not be processed.",
    );
  });

  it("formats lengths and sizes", () => {
    expect(formatDuration(65)).toBe("1:05");
    expect(formatDuration(3725)).toBe("1:02:05");
    expect(formatDuration(0)).toBe("0:00");
    expect(formatDuration(null)).toBe("");
    expect(formatDuration(-3)).toBe("");
    expect(formatDuration(Number.NaN)).toBe("");
    expect(formatSize(200)).toBe("1 KB");
    expect(formatSize(3 * 1024 * 1024)).toBe("3.0 MB");
    expect(formatSize(null)).toBe("");
  });

  it("names the languages", () => {
    expect(languageLabel("hi")).toBe("Hindi");
    expect(languageLabel("te")).toBe("Telugu");
    expect(languageLabel("en")).toBe("English");
    expect(languageLabel("fr")).toBe("fr");
  });

  it("accepts only an http(s) address for the audio player", () => {
    expect(safeAudioUrl("https://files.example/a?sig=1")).toBe(
      "https://files.example/a?sig=1",
    );
    expect(safeAudioUrl("http://localhost:9400/a")).toBe(
      "http://localhost:9400/a",
    );
    expect(safeAudioUrl("javascript:alert(1)")).toBeNull();
    expect(safeAudioUrl("data:audio/mp3;base64,AAAA")).toBeNull();
    expect(safeAudioUrl("/relative")).toBeNull();
    expect(safeAudioUrl("")).toBeNull();
  });

  it("refuses a tampered lead id", () => {
    expect(callsPath(LEAD)).toBe(`/leads/${LEAD}`);
    expect(() => callsPath("../../etc")).toThrow();
    expect(() => callsPath("")).toThrow();
  });

  it("gives plain words for the API's refusals", () => {
    expect(callErrorText("call_audio_unavailable", "x")).toMatch(
      /switched off/,
    );
    expect(callErrorText("call_limit_reached", "x")).toMatch(/Too many/);
    expect(callErrorText("call_not_audio", "x")).toMatch(/kind of audio/);
    expect(callErrorText("call_upload_expired", "x")).toMatch(/Start again/);
    expect(callErrorText("something_else", "The API said no.")).toBe(
      "The API said no.",
    );
  });
});

describe("checkNewCall", () => {
  const ok = {
    fileName: "call.MP3",
    size: 1000,
    language: "te",
    consent: true,
  };

  it("accepts a good recording and always sends consent as true", () => {
    expect(checkNewCall(ok)).toEqual({
      ok: true,
      body: { fileName: "call.MP3", size: 1000, language: "te", consent: true },
    });
  });

  it("needs the buyer's agreement - only a real true counts", () => {
    for (const consent of [false, undefined, null, "true", "on", 1]) {
      const result = checkNewCall({ ...ok, consent });
      expect(result.ok).toBe(false);
      if (!result.ok) expect(result.fieldErrors.consent).toMatch(/agreed/);
    }
  });

  it("needs a known language", () => {
    for (const language of ["", "fr", "HI", undefined]) {
      const result = checkNewCall({ ...ok, language });
      expect(result.ok).toBe(false);
      if (!result.ok) expect(result.fieldErrors.language).toBeDefined();
    }
  });

  it("needs an audio file name and a size within the limit", () => {
    for (const fileName of ["", "notes.pdf", "call.exe", "call", 5]) {
      const result = checkNewCall({ ...ok, fileName });
      expect(result.ok).toBe(false);
      if (!result.ok) expect(result.fieldErrors.file).toBeDefined();
    }
    for (const size of [0, -1, 1.5, "abc", undefined]) {
      expect(checkNewCall({ ...ok, size }).ok).toBe(false);
    }
    expect(checkNewCall({ ...ok, size: 100 * 1024 * 1024 }).ok).toBe(true);
    expect(checkNewCall({ ...ok, size: 100 * 1024 * 1024 + 1 }).ok).toBe(false);
  });

  it("reports every problem at once", () => {
    const result = checkNewCall({
      fileName: "",
      size: 0,
      language: "",
      consent: false,
    });
    expect(result.ok).toBe(false);
    if (!result.ok)
      expect(Object.keys(result.fieldErrors).sort()).toEqual([
        "consent",
        "file",
        "language",
      ]);
  });
});

describe("permissions for call recordings", () => {
  it("are display only and follow the two permissions", () => {
    expect(canReadCalls({ permissions: ["call:read"] })).toBe(true);
    expect(canReadCalls({ permissions: ["call:write"] })).toBe(false);
    expect(canWriteCalls({ permissions: ["call:write"] })).toBe(true);
    expect(canWriteCalls({ permissions: ["call:read"] })).toBe(false);
    expect(canReadCalls({ permissions: [] })).toBe(false);
  });
});

// --- the Server Actions ----------------------------------------------------------------------

describe("call Server Actions", () => {
  beforeEach(() => apiFetch.mockReset());

  const info = { fileName: "c.mp3", size: 1000, language: "hi", consent: true };

  it("starts an upload with only the fields the API accepts", async () => {
    apiFetch.mockResolvedValue({
      call_id: CALL,
      url: "https://store.example",
      fields: { key: "k" },
      expires_at: "2026-11-13T10:05:00Z",
      max_bytes: 1000,
    });
    const result = await startCallUpload(LEAD, {
      ...info,
      // Things a tampered client might add:
      tenant_id: "x",
      status: "ready",
      lead_id: "y",
    } as never);
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe(`/leads/${LEAD}/calls/uploads`);
    expect(JSON.parse(init.body)).toEqual({
      file_name: "c.mp3",
      size_bytes: 1000,
      language: "hi",
      consent: true,
    });
    expect(result).toEqual({
      ticket: {
        upload_id: CALL,
        url: "https://store.example",
        fields: { key: "k" },
        expires_at: "2026-11-13T10:05:00Z",
        max_bytes: 1000,
      },
    });
  });

  it("sends nothing when consent is missing or the file is wrong", async () => {
    for (const bad of [
      { ...info, consent: false },
      { ...info, fileName: "notes.pdf" },
      { ...info, language: "fr" },
      { ...info, size: 0 },
    ]) {
      const result = await startCallUpload(LEAD, bad);
      expect("fieldErrors" in result).toBe(true);
    }
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("refuses a tampered lead id before any request", async () => {
    await expect(startCallUpload("../x", info)).rejects.toThrow();
    await expect(
      finishCallUpload("../x", CALL, initialDialogState),
    ).rejects.toThrow();
    await expect(listenToCall("../x", CALL)).rejects.toThrow();
    await expect(readCallTranscript("../x", CALL)).rejects.toThrow();
    await expect(
      deleteCallAudio("../x", CALL, initialDialogState),
    ).rejects.toThrow();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("refuses a made-up recording id before any request", async () => {
    await expect(
      finishCallUpload(LEAD, "nope", initialDialogState),
    ).rejects.toThrow();
    await expect(listenToCall(LEAD, "nope")).rejects.toThrow();
    await expect(readCallTranscript(LEAD, "nope")).rejects.toThrow();
    await expect(
      deleteCallAudio(LEAD, "nope", initialDialogState),
    ).rejects.toThrow();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("explains an API refusal in plain words", async () => {
    apiFetch.mockRejectedValueOnce(problem(503, "call_audio_unavailable"));
    const result = await startCallUpload(LEAD, info);
    expect("error" in result && result.error?.message).toMatch(/switched off/);
  });

  it("finishing redirects to the card; a refusal keeps the dialog open", async () => {
    apiFetch.mockResolvedValueOnce({});
    await expect(
      finishCallUpload(LEAD, CALL, initialDialogState),
    ).rejects.toThrow(`REDIRECT:/leads/${LEAD}?done=call-added#calls`);
    expect(apiFetch).toHaveBeenCalledWith(
      `/leads/${LEAD}/calls/${CALL}/finish`,
      {
        method: "POST",
      },
    );
    apiFetch.mockRejectedValueOnce(problem(422, "call_not_audio"));
    const state = await finishCallUpload(LEAD, CALL, initialDialogState);
    expect(state.attempt).toBe(1);
    expect(state.error?.message).toMatch(/kind of audio/);
  });

  it("deleting the audio calls the audio endpoint and redirects", async () => {
    apiFetch.mockResolvedValueOnce({});
    await expect(
      deleteCallAudio(LEAD, CALL, initialDialogState),
    ).rejects.toThrow(`REDIRECT:/leads/${LEAD}?done=call-audio-deleted#calls`);
    expect(apiFetch).toHaveBeenCalledWith(
      `/leads/${LEAD}/calls/${CALL}/audio`,
      {
        method: "DELETE",
      },
    );
  });

  it("listening returns a link only when it is a normal web address", async () => {
    apiFetch.mockResolvedValueOnce({
      url: "https://store.example/a?sig=1",
      expires_in_seconds: 60,
      which: "cleaned",
    });
    expect(await listenToCall(LEAD, CALL)).toEqual({
      ok: true,
      value: {
        url: "https://store.example/a?sig=1",
        expires_in_seconds: 60,
        which: "cleaned",
      },
    });
    apiFetch.mockResolvedValueOnce({
      url: "javascript:alert(1)",
      expires_in_seconds: 60,
      which: "cleaned",
    });
    expect((await listenToCall(LEAD, CALL)).ok).toBe(false);
    apiFetch.mockRejectedValueOnce(problem(410, "call_audio_deleted"));
    const gone = await listenToCall(LEAD, CALL);
    expect(gone).toEqual({
      ok: false,
      message: "The audio of this recording was deleted.",
    });
  });

  it("reads the transcript on request", async () => {
    apiFetch.mockResolvedValueOnce(detail());
    const result = await readCallTranscript(LEAD, CALL);
    expect(apiFetch).toHaveBeenCalledWith(`/leads/${LEAD}/calls/${CALL}`);
    expect(result.ok && result.value.transcript).toMatch(/Namaste/);
    apiFetch.mockRejectedValueOnce(problem(404, "call_not_found"));
    expect((await readCallTranscript(LEAD, CALL)).ok).toBe(false);
  });
});

// --- the card ---------------------------------------------------------------------------------

function actions(changes: Partial<CallsActions> = {}): CallsActions {
  return {
    start: vi.fn(),
    finish: vi.fn(),
    deleteAudio: vi.fn(),
    listen: vi.fn().mockResolvedValue({
      ok: true,
      value: {
        url: "https://store.example/a?sig=1",
        expires_in_seconds: 60,
        which: "cleaned",
      },
    }),
    read: vi.fn().mockResolvedValue({ ok: true, value: detail() }),
    ...changes,
  };
}

describe("CallsView", () => {
  beforeEach(() => refresh.mockReset());
  afterEach(() => vi.useRealTimers());

  it("says so when there are no recordings, and offers adding one only to writers", () => {
    const { rerender } = render(
      <CallsView calls={[]} canWrite actions={actions()} />,
    );
    expect(screen.getByText(/No call recordings yet/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Add a call recording" }),
    ).toBeInTheDocument();
    rerender(<CallsView calls={[]} canWrite={false} actions={actions()} />);
    expect(
      screen.queryByRole("button", { name: "Add a call recording" }),
    ).toBeNull();
  });

  it("shows a ready recording with its facts and plays the cleaned copy on request", async () => {
    const a = actions();
    render(<CallsView calls={[call()]} canWrite actions={a} />);
    expect(screen.getByText("call 12 nov.mp3")).toBeInTheDocument();
    expect(screen.getByTestId("call-status")).toHaveTextContent(
      "Transcript ready",
    );
    expect(screen.getByText(/Hindi · 2:05 · 3\.0 MB/)).toBeInTheDocument();
    expect(document.querySelector("audio")).toBeNull(); // nothing is loaded until asked
    await userEvent.click(screen.getByRole("button", { name: "Listen" }));
    expect(a.listen).toHaveBeenCalledWith(CALL);
    const player = document.querySelector("audio") as HTMLAudioElement;
    expect(player.getAttribute("src")).toBe("https://store.example/a?sig=1");
    expect(screen.getByText(/background noise reduced/)).toBeInTheDocument();
  });

  it("shows the transcript as plain text with start times, marked as automatic", async () => {
    const a = actions({
      read: vi.fn().mockResolvedValue({
        ok: true,
        value: detail({
          segments: [
            { start: 65, end: 70, text: "<img src=x onerror=alert(1)> hello" },
          ],
        }),
      }),
    });
    render(<CallsView calls={[call()]} canWrite actions={a} />);
    await userEvent.click(
      screen.getByRole("button", { name: "Show transcript" }),
    );
    const panel = await screen.findByTestId("call-transcript");
    expect(panel).toHaveTextContent(/Automatic transcript/);
    expect(panel).toHaveTextContent("1:05");
    expect(panel).toHaveTextContent("<img src=x onerror=alert(1)> hello");
    expect(panel.querySelector("img")).toBeNull(); // shown as text, never as markup
    await userEvent.click(
      screen.getByRole("button", { name: "Hide transcript" }),
    );
    expect(screen.queryByTestId("call-transcript")).toBeNull();
  });

  it("reads the transcript once and shows an error in words when it cannot", async () => {
    const read = vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        message: "That recording was not found.",
      })
      .mockResolvedValue({ ok: true, value: detail() });
    render(<CallsView calls={[call()]} canWrite actions={actions({ read })} />);
    await userEvent.click(
      screen.getByRole("button", { name: "Show transcript" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("not found");
    await userEvent.click(
      screen.getByRole("button", { name: "Show transcript" }),
    );
    await screen.findByTestId("call-transcript");
    await userEvent.click(
      screen.getByRole("button", { name: "Hide transcript" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Show transcript" }),
    );
    expect(read).toHaveBeenCalledTimes(2); // the second answer was kept
  });

  it("shows why a failed recording failed", () => {
    render(
      <CallsView
        calls={[
          call({
            status: "failed",
            failure_code: "too_long",
            has_transcript: false,
          }),
        ]}
        canWrite
        actions={actions()}
      />,
    );
    expect(screen.getByText(/longer than the limit/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Listen" })).toBeNull();
    expect(screen.queryByRole("button", { name: /transcript/i })).toBeNull();
  });

  it("offers neither listening nor deleting while the worker has the recording", () => {
    render(
      <CallsView
        calls={[call({ status: "queued", has_transcript: false })]}
        canWrite
        actions={actions()}
      />,
    );
    expect(screen.getByTestId("call-status")).toHaveTextContent(
      /cleaned and transcribed/,
    );
    expect(screen.queryByRole("button", { name: "Listen" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete audio" })).toBeNull();
  });

  it("hides the delete button from readers and after the audio is gone", () => {
    const { rerender } = render(
      <CallsView calls={[call()]} canWrite={false} actions={actions()} />,
    );
    expect(screen.queryByRole("button", { name: "Delete audio" })).toBeNull();
    rerender(
      <CallsView
        calls={[
          call({
            audio_available: false,
            audio_deleted_at: "2026-11-13T12:00:00Z",
          }),
        ]}
        canWrite
        actions={actions()}
      />,
    );
    expect(screen.queryByRole("button", { name: "Delete audio" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Listen" })).toBeNull();
    expect(screen.getByText(/The audio was deleted on/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Show transcript" }),
    ).toBeInTheDocument();
  });

  it("deleting the audio asks first and then calls the action", async () => {
    const a = actions({
      deleteAudio: vi.fn().mockResolvedValue(initialDialogState),
    });
    render(<CallsView calls={[call()]} canWrite actions={a} />);
    await userEvent.click(screen.getByRole("button", { name: "Delete audio" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText(/can't be brought back/),
    ).toBeInTheDocument();
    expect(a.deleteAudio).not.toHaveBeenCalled();
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Delete audio" }),
    );
    await waitFor(() => expect(a.deleteAudio).toHaveBeenCalled());
    expect(a.deleteAudio).toHaveBeenCalledWith(CALL, expect.anything());
  });

  it("looks again every few seconds only while a recording is being processed", () => {
    vi.useFakeTimers();
    const { rerender } = render(
      <CallsView
        calls={[call({ status: "queued" })]}
        canWrite
        actions={actions()}
      />,
    );
    act(() => vi.advanceTimersByTime(REFRESH_MS * 2 + 10));
    expect(refresh).toHaveBeenCalledTimes(2);
    refresh.mockReset();
    rerender(<CallsView calls={[call()]} canWrite actions={actions()} />);
    act(() => vi.advanceTimersByTime(REFRESH_MS * 3));
    expect(refresh).not.toHaveBeenCalled();
  });

  it("stops looking when the card goes away", () => {
    vi.useFakeTimers();
    const { unmount } = render(
      <CallsView
        calls={[call({ status: "queued" })]}
        canWrite
        actions={actions()}
      />,
    );
    unmount();
    act(() => vi.advanceTimersByTime(REFRESH_MS * 3));
    expect(refresh).not.toHaveBeenCalled();
  });

  it("shows a file name as text, never as markup", () => {
    render(
      <CallsView
        calls={[call({ file_name: "<b>bold</b>.mp3" })]}
        canWrite
        actions={actions()}
      />,
    );
    expect(screen.getByText("<b>bold</b>.mp3")).toBeInTheDocument();
    expect(document.querySelector("li b")).toBeNull();
  });
});

describe("the add dialog", () => {
  it("needs the buyer's agreement ticked and shows the three languages", async () => {
    render(<CallsView calls={[]} canWrite actions={actions()} />);
    await userEvent.click(
      screen.getByRole("button", { name: "Add a call recording" }),
    );
    const dialog = await screen.findByRole("dialog");
    const options = within(dialog)
      .getAllByRole("option")
      .map((o) => (o as HTMLOptionElement).value);
    expect(options).toEqual(["hi", "te", "en"]);
    const consent = within(dialog).getByRole("checkbox", {
      name: /buyer agreed/,
    }) as HTMLInputElement;
    expect(consent.checked).toBe(false); // never ticked for the person
  });

  it("sends nothing and keeps the form when no recording is chosen", async () => {
    const a = actions();
    render(<CallsView calls={[]} canWrite actions={a} />);
    await userEvent.click(
      screen.getByRole("button", { name: "Add a call recording" }),
    );
    const dialog = await screen.findByRole("dialog");
    await userEvent.selectOptions(
      within(dialog).getByLabelText(/Language/),
      "te",
    );
    await userEvent.click(
      within(dialog).getByRole("checkbox", { name: /buyer agreed/ }),
    );
    // The file input is required, so the browser stops the submit; submit the form directly.
    const form = dialog.querySelector("form") as HTMLFormElement;
    await act(async () => form.requestSubmit?.());
    expect(a.start).not.toHaveBeenCalled();
    expect(
      (within(dialog).getByLabelText(/Language/) as HTMLSelectElement).value,
    ).toBe("te");
    expect(
      (
        within(dialog).getByRole("checkbox", {
          name: /buyer agreed/,
        }) as HTMLInputElement
      ).checked,
    ).toBe(true);
  });
});

describe("TranscriptPanel", () => {
  it("falls back to the plain text when there are no segments", () => {
    render(<TranscriptPanel detail={detail({ segments: [] })} />);
    expect(screen.getByTestId("call-transcript")).toHaveTextContent(
      "Namaste. Nenu flat kavali.",
    );
  });
});

describe("the content security policy", () => {
  it("lets the player load audio from the file store", async () => {
    vi.stubEnv("FILE_STORE_ORIGIN", "https://storage.googleapis.com/");
    vi.resetModules();
    const config = (await import("../../next.config")).default;
    const headers = (await config.headers!()).flatMap((r) => r.headers);
    const policy = headers.find(
      (h) => h.key === "Content-Security-Policy-Report-Only",
    )!.value;
    expect(policy).toContain("media-src 'self' https://storage.googleapis.com");
    vi.stubEnv("FILE_STORE_ORIGIN", "");
    vi.resetModules();
    const bare = (await import("../../next.config")).default;
    const plain = (await bare.headers!())
      .flatMap((r) => r.headers)
      .find((h) => h.key === "Content-Security-Policy-Report-Only")!.value;
    expect(plain).not.toContain("media-src");
    vi.unstubAllEnvs();
  });
});

describe("dialogs that stay mounted after their action worked", () => {
  it("the delete dialog closes when the page shows the audio is gone", async () => {
    const a = actions();
    const { rerender } = render(
      <CallsView calls={[call()]} canWrite actions={a} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Delete audio" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    rerender(
      <CallsView
        calls={[
          call({
            audio_available: false,
            audio_deleted_at: "2026-11-13T12:00:00Z",
          }),
        ]}
        canWrite
        actions={a}
      />,
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("the add dialog closes when the new recording appears, not when a status changes", async () => {
    const a = actions();
    const waiting = call({ status: "queued", has_transcript: false });
    const { rerender } = render(
      <CallsView calls={[waiting]} canWrite actions={a} />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Add a call recording" }),
    );
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    // The worker finished the other recording while the dialog was open: it stays open.
    rerender(<CallsView calls={[call()]} canWrite actions={a} />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    // A new recording was added: the dialog closes.
    rerender(
      <CallsView
        calls={[
          call({
            id: "33333333-3333-4333-8333-333333333333",
            status: "queued",
          }),
          call(),
        ]}
        canWrite
        actions={a}
      />,
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createNotes,
  makeProposals,
  previewProposals,
  readNotes,
  readNotesVersion,
} from "@/app/(app)/leads/[id]/call-notes-actions";
import { saveFrame } from "@/app/(app)/automation/call-notes/actions";
import {
  CallNotesPanel,
  type NotesActions,
} from "@/components/call-notes-panel";
import { CallNotesSettingsForm } from "@/components/call-notes-settings-form";
import { agentLabel } from "@/components/approval-views";
import { CallsView, type CallsActions } from "@/components/calls-views";
import { ApiError } from "@/lib/api-error";
import {
  checkFramework,
  checkPositions,
  cleanedText,
  noteCodeText,
  notesErrorText,
  outcomeText,
  stamp,
  type CallNotesSettings,
  type NotesDraft,
  type NotesLine,
  type NotesPage,
  type ProposalOutcome,
  type ProposalPreview,
} from "@/lib/call-notes";
import type { CallDetail, CallRecording } from "@/lib/calls";
import { initialFormState } from "@/lib/form-state";
import {
  canManageCallNotes,
  canRunCallNotes,
  navigationFor,
  PERMISSION_LABELS,
} from "@/lib/permissions";

const apiFetch = vi.fn();
vi.mock("@/lib/server/api", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}));
const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`REDIRECT:${to}`);
  },
  useRouter: () => ({ refresh }),
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

function line(changes: Partial<NotesLine> = {}): NotesLine {
  return {
    position: 1,
    field: "budget",
    label: "Budget",
    state: "stated",
    value: "around one and a half crore",
    quote: "My budget is around one and a half crore",
    start_ms: 6000,
    end_ms: 14000,
    reason: null,
    note_code: null,
    ...changes,
  };
}

function draft(changes: Partial<NotesDraft> = {}): NotesDraft {
  return {
    id: "33333333-3333-4333-8333-333333333333",
    version_no: 1,
    framework: "bant",
    requested_by_user_id: "44444444-4444-4444-8444-444444444444",
    model_name: "scripted",
    downgraded: 0,
    dropped_notes: 0,
    cleaned_codes: [],
    created_at: "2026-11-20T09:00:00Z",
    lines: [
      line(),
      line({
        position: 2,
        field: "authority",
        label: "Authority",
        state: "assumed",
        value: "wife decides too",
        quote: "My wife and I decide together",
        start_ms: 14000,
        reason: "They said 'we decide together'.",
      }),
      line({
        position: 3,
        field: "need",
        label: "Need",
        state: "unknown",
        value: null,
        quote: null,
        start_ms: null,
        end_ms: null,
      }),
    ],
    ...changes,
  };
}

function pageOf(...drafts: NotesDraft[]): NotesPage {
  const newest = drafts[0] ?? null;
  return {
    newest,
    versions: drafts.map((d) => ({
      version_no: d.version_no,
      framework: d.framework,
      requested_by_user_id: d.requested_by_user_id,
      created_at: d.created_at,
    })),
  };
}

const PREVIEW: ProposalPreview = {
  memory: [
    {
      position: 1,
      field: "budget",
      label: "Budget",
      key: "budget",
      value: "around one and a half crore",
      note: 'Said on the call at 0:06: "My budget..."',
    },
    {
      position: 2,
      field: "authority",
      label: "Authority",
      key: "decision_makers",
      value: "wife decides too",
      note: "They hinted at it. (call, 0:14)",
    },
  ],
  task: { subject: "Ask the buyer about need", due_in_days: 2 },
};

function actions(overrides: Partial<NotesActions> = {}): NotesActions {
  return {
    read: vi.fn().mockResolvedValue({ ok: true, value: pageOf(draft()) }),
    readVersion: vi.fn().mockResolvedValue({ ok: true, value: draft() }),
    create: vi.fn().mockResolvedValue({ ok: true, value: draft() }),
    preview: vi.fn().mockResolvedValue({ ok: true, value: PREVIEW }),
    propose: vi.fn().mockResolvedValue({ ok: true, value: [] }),
    ...overrides,
  };
}

function panel(
  a: NotesActions,
  options: { canAsk?: boolean; audio?: boolean; listen?: () => unknown } = {},
) {
  return render(
    <CallNotesPanel
      actions={a}
      canAsk={options.canAsk ?? true}
      audioAvailable={options.audio ?? true}
      listen={
        (options.listen as never) ??
        (vi.fn().mockResolvedValue({
          ok: true,
          value: {
            url: "https://store.example/a?sig=1",
            expires_in_seconds: 60,
            which: "cleaned",
          },
        }) as never)
      }
    />,
  );
}

beforeEach(() => {
  apiFetch.mockReset();
  refresh.mockReset();
});

// --- helpers ----------------------------------------------------------------------------------

describe("call notes helpers", () => {
  it("writes a moment as minutes and seconds", () => {
    expect(stamp(6000)).toBe("0:06");
    expect(stamp(3_725_000)).toBe("62:05");
    expect(stamp(null)).toBe("");
    expect(stamp(-5)).toBe("0:00");
  });

  it("explains why a line was turned into unknown, in words", () => {
    expect(noteCodeText(null)).toBeNull();
    expect(noteCodeText("quote_not_found")).toMatch(/not in the transcript/);
    expect(noteCodeText("value_not_in_quote")).toMatch(/not part of the words/);
    expect(noteCodeText("quote_too_short")).toMatch(/too short/);
    expect(noteCodeText("bad_time")).toMatch(/moment/);
    expect(noteCodeText("something_new")).toMatch(/could not be checked/);
  });

  it("describes what was cleaned without repeating any text", () => {
    expect(cleanedText(["link", "instruction_phrase"])).toEqual([
      "A link was removed.",
      "Some words read like instructions to an AI. They were treated only as words somebody said.",
    ]);
    expect(cleanedText([])).toEqual([]);
  });

  it("turns the API's codes into plain sentences", () => {
    expect(notesErrorText("agent_unavailable", "x")).toMatch(/switched off/);
    expect(notesErrorText("agent_budget_reached", "x")).toMatch(/budget/);
    expect(notesErrorText("call_notes_rate_limited", "x")).toMatch(/too often/);
    expect(notesErrorText("call_notes_unverified_answer", "x")).toMatch(
      /nothing was saved/,
    );
    expect(notesErrorText("call_notes_settings_conflict", "x")).toMatch(
      /Reload/,
    );
    expect(notesErrorText("other", "Server words")).toBe("Server words");
  });

  it("says what happened to each suggestion", () => {
    const base: ProposalOutcome = {
      target: "budget",
      position: 1,
      status: "proposed",
      proposal_id: "p",
      proposal_link: "/approvals/p",
      message: null,
    };
    expect(outcomeText(base)).toMatch(/different person/);
    expect(
      outcomeText({
        ...base,
        status: "blocked",
        message: "A link is not allowed.",
      }),
    ).toBe("Not sent: A link is not allowed.");
    expect(
      outcomeText({
        ...base,
        status: "refused",
        message: "Already confirmed.",
      }),
    ).toBe("Not sent: Already confirmed.");
    expect(outcomeText({ ...base, status: "skipped" })).toMatch(/too many/);
  });

  it("accepts only whole line numbers from 1, without repeats", () => {
    expect(checkPositions(null)).toEqual({ ok: true, value: null });
    expect(checkPositions([])).toEqual({ ok: true, value: [] });
    expect(checkPositions([1, 3])).toEqual({ ok: true, value: [1, 3] });
    for (const bad of [[0], [1.5], ["1"], [1, 1], "1", new Array(21).fill(1)])
      expect(checkPositions(bad).ok).toBe(false);
  });

  it("accepts only the two known frames", () => {
    expect(checkFramework("bant")).toEqual({ ok: true, value: "bant" });
    expect(checkFramework("meddic")).toEqual({ ok: true, value: "meddic" });
    for (const bad of ["spin", "", null, undefined, "BANT"])
      expect(checkFramework(bad).ok).toBe(false);
  });
});

describe("permissions and labels", () => {
  it("shows the settings page entry to administrators only", () => {
    const admin = { permissions: ["call_notes:manage", "call_notes:run"] };
    const agent = { permissions: ["call_notes:run"] };
    expect(canManageCallNotes(admin)).toBe(true);
    expect(canManageCallNotes(agent)).toBe(false);
    expect(canRunCallNotes(agent)).toBe(true);
    const labels = (me: { permissions: string[] }) =>
      navigationFor({ ...me, user_type: "staff" } as never).map((i) => i.label);
    expect(labels(admin)).toContain("Call notes");
    expect(labels(agent)).not.toContain("Call notes");
  });

  it("has words for both permissions on the profile page", () => {
    expect(PERMISSION_LABELS["call_notes:run"]).toMatch(/call notes/i);
    expect(PERMISSION_LABELS["call_notes:manage"]).toMatch(/BANT/);
  });

  it("names the call notes agent on an approval", () => {
    expect(agentLabel({ agent: "call_notes", custom_agent_name: null })).toBe(
      "the call notes agent",
    );
  });
});

// --- Server Actions ---------------------------------------------------------------------------

describe("call notes Server Actions", () => {
  it("reads the notes of one call and one version", async () => {
    apiFetch.mockResolvedValueOnce(pageOf(draft()));
    const page = await readNotes(LEAD, CALL);
    expect(apiFetch).toHaveBeenCalledWith(`/leads/${LEAD}/calls/${CALL}/notes`);
    expect(page.ok).toBe(true);
    apiFetch.mockResolvedValueOnce(draft());
    await readNotesVersion(LEAD, CALL, 2);
    expect(apiFetch).toHaveBeenLastCalledWith(
      `/leads/${LEAD}/calls/${CALL}/notes/2`,
    );
  });

  it("asks for notes with NO body: the server knows the lead, the call and the frame", async () => {
    apiFetch.mockResolvedValueOnce(draft());
    await createNotes(LEAD, CALL);
    expect(apiFetch).toHaveBeenCalledWith(
      `/leads/${LEAD}/calls/${CALL}/notes`,
      {
        method: "POST",
      },
    );
  });

  it("previews with the follow-up choice only", async () => {
    apiFetch.mockResolvedValueOnce(PREVIEW);
    await previewProposals(LEAD, CALL, 1, false);
    expect(apiFetch).toHaveBeenCalledWith(
      `/leads/${LEAD}/calls/${CALL}/notes/1/proposals/preview?follow_up_task=false`,
    );
  });

  it("sends only the chosen line numbers and the task choice - never a key, a value or an id", async () => {
    apiFetch.mockResolvedValueOnce({ items: [] });
    await makeProposals(LEAD, CALL, 2, {
      positions: [1, 3],
      followUpTask: false,
      // @ts-expect-error - what a tampered browser might add; it must not be forwarded
      key: "budget",
      tenant_id: "x",
    });
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe(`/leads/${LEAD}/calls/${CALL}/notes/2/proposals`);
    expect(JSON.parse(init.body)).toEqual({
      positions: [1, 3],
      follow_up_task: false,
    });
  });

  it("refuses bad line numbers before anything is sent", async () => {
    const result = await makeProposals(LEAD, CALL, 1, {
      positions: [0],
      followUpTask: true,
    });
    expect(result.ok).toBe(false);
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("throws for a tampered id or version instead of calling the API", async () => {
    await expect(readNotes("../x", CALL)).rejects.toThrow("invalid lead");
    await expect(createNotes(LEAD, "nope")).rejects.toThrow(
      "invalid recording",
    );
    await expect(readNotesVersion(LEAD, CALL, 0)).rejects.toThrow(
      "invalid version",
    );
    await expect(
      makeProposals(LEAD, CALL, 1.5 as never, {
        positions: null,
        followUpTask: true,
      }),
    ).rejects.toThrow("invalid version");
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("explains a refusal in plain words", async () => {
    apiFetch.mockRejectedValueOnce(problem(503, "agent_unavailable"));
    const result = await createNotes(LEAD, CALL);
    expect(result).toEqual({
      ok: false,
      message: expect.stringMatching(/switched off/),
    });
    apiFetch.mockRejectedValueOnce(
      problem(422, "call_notes_unverified_answer"),
    );
    const second = await createNotes(LEAD, CALL);
    expect(second.ok).toBe(false);
  });
});

// --- the panel --------------------------------------------------------------------------------

describe("CallNotesPanel", () => {
  it("labels the draft and shows each line with its state, quote, moment and the speaker warning", async () => {
    panel(actions());
    const lines = await screen.findAllByTestId("notes-line");
    expect(lines).toHaveLength(3);
    expect(screen.getByTestId("call-notes")).toHaveTextContent(/An AI draft/);
    expect(screen.getByTestId("call-notes")).toHaveTextContent(
      /Nothing in the CRM has changed/,
    );
    expect(within(lines[0]).getByTestId("notes-state")).toHaveTextContent(
      "Stated",
    );
    expect(lines[0]).toHaveTextContent("around one and a half crore");
    expect(lines[0]).toHaveTextContent("At 0:06");
    expect(lines[0]).toHaveTextContent("Speaker not verified");
    expect(within(lines[1]).getByTestId("notes-state")).toHaveTextContent(
      "Assumed",
    );
    expect(lines[1]).toHaveTextContent("Why we think so:");
    expect(within(lines[2]).getByTestId("notes-state")).toHaveTextContent(
      "Unknown",
    );
    expect(lines[2]).toHaveTextContent("Nothing on this call answers it.");
    expect(lines[2]).not.toHaveTextContent("Speaker not verified");
  });

  it("shows words from the transcript or the AI as plain text, never as markup", async () => {
    const poisoned = draft({
      lines: [
        line({
          value: "<b>bold</b>",
          quote: "<img src=x onerror=alert(1)> crore",
        }),
      ],
    });
    panel(
      actions({
        read: vi.fn().mockResolvedValue({ ok: true, value: pageOf(poisoned) }),
      }),
    );
    const quote = await screen.findByTestId("notes-quote");
    expect(quote).toHaveTextContent("<img src=x onerror=alert(1)> crore");
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("b")).toBeNull();
  });

  it("explains a line the code turned into unknown", async () => {
    const d = draft({
      downgraded: 1,
      lines: [
        line({
          state: "unknown",
          value: null,
          quote: null,
          start_ms: null,
          end_ms: null,
          note_code: "quote_not_found",
        }),
      ],
    });
    panel(
      actions({
        read: vi.fn().mockResolvedValue({ ok: true, value: pageOf(d) }),
      }),
    );
    expect(
      await screen.findByText(/not in the transcript/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/1 answer could not be checked/),
    ).toBeInTheDocument();
  });

  it("lists call notes, left-out notes and what was cleaned", async () => {
    const d = draft({
      dropped_notes: 2,
      cleaned_codes: ["link"],
      lines: [
        ...draft().lines,
        line({
          position: 4,
          field: "note",
          label: "Note",
          value: "Wants a flat near Kokapet",
          quote: "a two bedroom flat near Kokapet",
          start_ms: 30000,
        }),
      ],
    });
    panel(
      actions({
        read: vi.fn().mockResolvedValue({ ok: true, value: pageOf(d) }),
      }),
    );
    expect(await screen.findByTestId("notes-note")).toHaveTextContent(
      "Wants a flat near Kokapet",
    );
    expect(screen.getByText(/2 notes left out/)).toBeInTheDocument();
    expect(screen.getByText("A link was removed.")).toBeInTheDocument();
  });

  it("plays the recording at the moment of a quote", async () => {
    const listen = vi.fn().mockResolvedValue({
      ok: true,
      value: {
        url: "https://store.example/a?sig=1",
        expires_in_seconds: 60,
        which: "cleaned",
      },
    });
    panel(actions(), { listen });
    const first = (await screen.findAllByTestId("notes-line"))[0];
    await userEvent.click(
      within(first).getByRole("button", { name: "Listen at 0:06" }),
    );
    const player = document.querySelector("audio") as HTMLAudioElement;
    expect(player.getAttribute("src")).toBe(
      "https://store.example/a?sig=1#t=6",
    );
    expect(listen).toHaveBeenCalledTimes(1);
  });

  it("offers no listen buttons when the audio is gone", async () => {
    panel(actions(), { audio: false });
    await screen.findAllByTestId("notes-line");
    expect(screen.queryByRole("button", { name: /Listen at/ })).toBeNull();
  });

  it("says so when there are no notes yet and offers to create them only to people who may ask", async () => {
    const empty = actions({
      read: vi.fn().mockResolvedValue({ ok: true, value: pageOf() }),
    });
    const { unmount } = panel(empty);
    expect(await screen.findByText(/No call notes yet/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Create call notes" }),
    ).toBeInTheDocument();
    unmount();
    panel(empty, { canAsk: false });
    await screen.findByText(/No call notes yet/);
    expect(screen.queryByRole("button", { name: /call notes$/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Suggest/ })).toBeNull();
  });

  it("creates notes and shows the new draft with a list of versions", async () => {
    const a = actions({
      read: vi.fn().mockResolvedValue({ ok: true, value: pageOf() }),
      create: vi.fn().mockResolvedValue({ ok: true, value: draft() }),
    });
    panel(a);
    await userEvent.click(
      await screen.findByRole("button", { name: "Create call notes" }),
    );
    expect(a.create).toHaveBeenCalledTimes(1);
    expect(await screen.findByTestId("notes-draft")).toHaveTextContent(
      "BANT checklist · version 1",
    );
    expect(
      screen.getByRole("button", { name: "Make new call notes" }),
    ).toBeInTheDocument();
  });

  it("shows the refusal in words and keeps what was on screen", async () => {
    const a = actions({
      create: vi.fn().mockResolvedValue({
        ok: false,
        message: "Call notes are switched off for your organisation.",
      }),
    });
    panel(a);
    await screen.findByTestId("notes-draft");
    await userEvent.click(
      screen.getByRole("button", { name: "Make new call notes" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/switched off/);
    expect(screen.getByTestId("notes-draft")).toBeInTheDocument();
  });

  it("switches between versions", async () => {
    const second = draft({ version_no: 2 });
    const a = actions({
      read: vi
        .fn()
        .mockResolvedValue({ ok: true, value: pageOf(second, draft()) }),
      readVersion: vi.fn().mockResolvedValue({ ok: true, value: draft() }),
    });
    panel(a);
    await screen.findByTestId("notes-draft");
    expect(screen.getByTestId("notes-draft")).toHaveTextContent("version 2");
    await userEvent.click(screen.getByRole("button", { name: "1" }));
    expect(a.readVersion).toHaveBeenCalledWith(1);
    await waitFor(() =>
      expect(screen.getByTestId("notes-draft")).toHaveTextContent("version 1"),
    );
  });

  it("loads the notes once, not on every render", async () => {
    const a = actions();
    const { rerender } = panel(a);
    await screen.findByTestId("notes-draft");
    rerender(
      <CallNotesPanel
        actions={a}
        canAsk
        audioAvailable
        listen={vi.fn() as never}
      />,
    );
    expect(a.read).toHaveBeenCalledTimes(1);
  });

  it("shows a refusal to read the notes", async () => {
    panel(
      actions({
        read: vi.fn().mockResolvedValue({
          ok: false,
          message: "That recording was not found.",
        }),
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("not found");
  });
});

describe("suggesting to the buyer memory", () => {
  async function open(a: NotesActions) {
    panel(a);
    await userEvent.click(
      await screen.findByRole("button", { name: "Suggest to buyer memory…" }),
    );
    await screen.findByText(/assumptions, not facts/);
  }

  it("previews what would be suggested and says it is an assumption that needs a different person", async () => {
    const a = actions();
    await open(a);
    expect(a.preview).toHaveBeenCalledWith(1, true);
    const box = screen.getByTestId("notes-suggest");
    expect(box).toHaveTextContent("Budget: around one and a half crore");
    expect(box).toHaveTextContent("Authority: wife decides too");
    expect(box).toHaveTextContent("Follow-up task: Ask the buyer about need");
    expect(box).toHaveTextContent(/nothing changes until then/);
    for (const checkbox of within(box).getAllByRole("checkbox"))
      expect(checkbox).toBeChecked();
  });

  it("sends only what is still ticked", async () => {
    const outcomes: ProposalOutcome[] = [
      {
        target: "budget",
        position: 1,
        status: "proposed",
        proposal_id: "p1",
        proposal_link: "/approvals/p1",
        message: null,
      },
    ];
    const a = actions({
      propose: vi.fn().mockResolvedValue({ ok: true, value: outcomes }),
    });
    await open(a);
    await userEvent.click(screen.getByLabelText(/Authority: wife decides too/));
    await userEvent.click(screen.getByLabelText(/Follow-up task/));
    await userEvent.click(
      screen.getByRole("button", { name: "Send for approval" }),
    );
    expect(a.propose).toHaveBeenCalledWith(1, {
      positions: [1],
      followUpTask: false,
    });
    const done = await screen.findByTestId("notes-outcomes");
    expect(done).toHaveTextContent("Nothing has changed yet");
    expect(done).toHaveTextContent("Waiting for a different person");
    expect(within(done).getByRole("link", { name: "Open it" })).toHaveAttribute(
      "href",
      "/approvals/p1",
    );
  });

  it("cannot be sent with nothing ticked", async () => {
    await open(actions());
    for (const checkbox of screen.getAllByRole("checkbox"))
      await userEvent.click(checkbox);
    expect(
      screen.getByRole("button", { name: "Send for approval" }),
    ).toBeDisabled();
  });

  it("reports a line the safety check refused, with its reason, without a link", async () => {
    const outcomes: ProposalOutcome[] = [
      {
        target: "budget",
        position: 1,
        status: "blocked",
        proposal_id: null,
        proposal_link: null,
        message:
          "The text contains words that read like instructions to an AI.",
      },
      {
        target: "task",
        position: null,
        status: "skipped",
        proposal_id: null,
        proposal_link: null,
        message: "Too many proposals are waiting.",
      },
    ];
    const a = actions({
      propose: vi.fn().mockResolvedValue({ ok: true, value: outcomes }),
    });
    await open(a);
    await userEvent.click(
      screen.getByRole("button", { name: "Send for approval" }),
    );
    const done = await screen.findByTestId("notes-outcomes");
    expect(done).toHaveTextContent("Not sent: The text contains words");
    expect(done).toHaveTextContent("Follow-up task:");
    expect(within(done).queryByRole("link")).toBeNull();
    expect(done.querySelectorAll("a")).toHaveLength(0); // not even an empty anchor
  });

  it("says when there is nothing to suggest", async () => {
    const a = actions({
      preview: vi
        .fn()
        .mockResolvedValue({ ok: true, value: { memory: [], task: null } }),
    });
    panel(a);
    await userEvent.click(
      await screen.findByRole("button", { name: "Suggest to buyer memory…" }),
    );
    expect(
      await screen.findByText(/nothing in this draft to suggest/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Send for approval" }),
    ).toBeDisabled();
  });

  it("shows a refusal and can be cancelled", async () => {
    const a = actions({
      propose: vi.fn().mockResolvedValue({
        ok: false,
        message: "Too many suggestions are waiting for a decision.",
      }),
    });
    await open(a);
    await userEvent.click(
      screen.getByRole("button", { name: "Send for approval" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/Too many/);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(
      screen.getByRole("button", { name: "Suggest to buyer memory…" }),
    ).toBeInTheDocument();
  });
});

// --- inside the call card ---------------------------------------------------------------------

const RECORDING: CallRecording = {
  id: CALL,
  lead_id: LEAD,
  language: "en",
  status: "ready",
  failure_code: null,
  file_name: "call.mp3",
  size_bytes: 2000,
  duration_seconds: 90,
  consent_confirmed_at: "2026-11-20T08:00:00Z",
  created_at: "2026-11-20T08:00:00Z",
  finished_at: "2026-11-20T08:01:00Z",
  audio_available: true,
  audio_deleted_at: null,
  has_transcript: true,
  engine: "fake",
};
const DETAIL: CallDetail = {
  ...RECORDING,
  transcript: "Hello. My budget is one point two crore.",
  segments: [{ start: 6, end: 14, text: "My budget is one point two crore." }],
};

function callsActions(extra: Partial<CallsActions> = {}): CallsActions {
  return {
    start: vi.fn(),
    finish: vi.fn(),
    deleteAudio: vi.fn(),
    listen: vi.fn(),
    read: vi.fn().mockResolvedValue({ ok: true, value: DETAIL }),
    ...extra,
  };
}

const notesProps = (): Partial<CallsActions> => ({
  readNotes: vi.fn().mockResolvedValue({ ok: true, value: pageOf(draft()) }),
  readNotesVersion: vi.fn(),
  createNotes: vi.fn(),
  previewProposals: vi.fn(),
  makeProposals: vi.fn(),
});

describe("the call card", () => {
  it("shows the notes block under an open transcript, for this recording", async () => {
    const a = callsActions(notesProps());
    render(<CallsView calls={[RECORDING]} canWrite canAskNotes actions={a} />);
    expect(screen.queryByTestId("call-notes")).toBeNull(); // nothing until the transcript is open
    await userEvent.click(
      screen.getByRole("button", { name: "Show transcript" }),
    );
    await screen.findByTestId("call-notes");
    expect(a.readNotes).toHaveBeenCalledWith(CALL);
  });

  it("shows no notes block when the card was not given the notes actions", async () => {
    render(
      <CallsView
        calls={[RECORDING]}
        canWrite
        canAskNotes
        actions={callsActions()}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Show transcript" }),
    );
    await screen.findByTestId("call-transcript");
    expect(screen.queryByTestId("call-notes")).toBeNull();
  });

  it("does not offer asking to people who may not ask", async () => {
    render(
      <CallsView
        calls={[RECORDING]}
        canWrite
        canAskNotes={false}
        actions={callsActions(notesProps())}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Show transcript" }),
    );
    await screen.findByTestId("notes-draft");
    expect(screen.queryByRole("button", { name: /call notes$/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Suggest/ })).toBeNull();
  });
});

// --- the settings page ------------------------------------------------------------------------

const SETTINGS: CallNotesSettings = {
  framework: "bant",
  version: 0,
  frameworks: [
    {
      key: "bant",
      title: "BANT",
      fields: [
        { key: "budget", label: "Budget", hint: "h" },
        { key: "authority", label: "Authority", hint: "h" },
      ],
    },
    {
      key: "meddic",
      title: "MEDDIC",
      fields: [{ key: "metrics", label: "Metrics", hint: "h" }],
    },
  ],
};

describe("the settings form", () => {
  it("lists both frames with their fields and starts on the chosen one", () => {
    render(
      <CallNotesSettingsForm
        settings={{ ...SETTINGS, framework: "meddic" }}
        initialState={initialFormState}
        action={vi.fn()}
      />,
    );
    expect(screen.getByLabelText(/BANT/)).not.toBeChecked();
    expect(screen.getByLabelText(/MEDDIC/)).toBeChecked();
    expect(screen.getByText("Budget, Authority")).toBeInTheDocument();
  });

  it("keeps the choice after a refused save and explains it", async () => {
    const action = vi.fn().mockResolvedValue({
      attempt: 1,
      values: { framework: "meddic" },
      fieldErrors: {},
      error: {
        status: 409,
        message:
          "Someone else changed this setting. Reload the page and try again.",
        code: "call_notes_settings_conflict",
        requestId: null,
        fieldErrors: {},
      },
    });
    render(
      <CallNotesSettingsForm
        settings={SETTINGS}
        initialState={initialFormState}
        action={action}
      />,
    );
    await userEvent.click(screen.getByLabelText(/MEDDIC/));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Someone else changed/)).toBeInTheDocument();
    expect(screen.getByLabelText(/MEDDIC/)).toBeChecked();
  });
});

describe("the settings Server Action", () => {
  const previous = { ...initialFormState };
  const form = (framework: string) => {
    const data = new FormData();
    data.set("framework", framework);
    data.set("tenant_id", "x");
    return data;
  };

  it("sends only the frame and the version that was seen", async () => {
    apiFetch.mockResolvedValueOnce({});
    await expect(saveFrame(3, previous, form("meddic"))).rejects.toThrow(
      "REDIRECT:/automation/call-notes?done=saved",
    );
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe("/call-notes/settings");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({ framework: "meddic", version: 3 });
  });

  it("refuses an unknown frame before calling the API", async () => {
    const state = await saveFrame(0, previous, form("spin"));
    expect(state.fieldErrors.framework).toMatch(/BANT or MEDDIC/);
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("explains a stale version and keeps the choice", async () => {
    apiFetch.mockRejectedValueOnce(
      problem(409, "call_notes_settings_conflict"),
    );
    const state = await saveFrame(0, previous, form("meddic"));
    expect(state.values.framework).toBe("meddic");
    expect(state.error?.message).toMatch(/Reload/);
  });

  it("throws for a tampered version", async () => {
    await expect(saveFrame(-1, previous, form("bant"))).rejects.toThrow(
      "invalid version",
    );
  });
});

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  draftVideoScript,
  proposeVideoScript,
} from "@/app/print/leads/[id]/video-brief/actions";
import VideoBriefPage from "@/app/print/leads/[id]/video-brief/page";
import { SavedScripts } from "@/components/saved-scripts";
import { VideoScriptEditor } from "@/components/video-script-editor";
import { ApiError } from "@/lib/api-error";
import type { ScriptRead, VideoBrief } from "@/lib/api-types";
import { initialDialogState } from "@/lib/dialog-state";
import { strictChoices } from "@/lib/video-brief";
import {
  initialDraftState,
  scriptErrorText,
  type DraftState,
} from "@/lib/video-scripts";

const apiFetch = vi.fn();
const getMe = vi.fn();
vi.mock("@/lib/server/api", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
  getMe: () => getMe(),
}));
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NOT_FOUND");
  },
  redirect: (to: string) => {
    throw new Error(`REDIRECT:${to}`);
  },
}));
vi.mock("@/components/print-button", () => ({
  PrintButton: () => <button type="button">Print / Save as PDF</button>,
}));

const LEAD = "11111111-1111-4111-8111-111111111111";
const QUOTE = "22222222-2222-4222-8222-222222222222";
const PROPOSAL = "55555555-5555-4555-8555-555555555555";

function problem(status: number, code: string, detail = "Server words") {
  return new ApiError(status, {
    title: "x",
    status,
    detail,
    code,
    request_id: "r",
  });
}

function brief(changes: Partial<VideoBrief> = {}): VideoBrief {
  return {
    first_name: "Suresh",
    language: "en",
    tone: "warm",
    tone_note: "Speak warmly.",
    goal: "follow_up",
    length_seconds: 60,
    word_target: 150,
    words: 12,
    known: [],
    script: [
      { kind: "greeting", text: "Hello Suresh,", cites: [], seconds: 1 },
      { kind: "closing", text: "Thank you.", cites: [], seconds: 1 },
    ],
    must_say: ["Say the RERA number."],
    must_not_say: ["Never promise guaranteed returns."],
    consent_notes: ["Check consent."],
    cautions: [],
    ...changes,
  };
}

function saved(changes: Partial<ScriptRead> = {}): ScriptRead {
  return {
    id: "33333333-3333-4333-8333-333333333333",
    version: 1,
    source: "hand_written",
    language: "en",
    tone: "warm",
    goal: "follow_up",
    length_seconds: 60,
    lines: ["Hello Suresh,", "Thank you."],
    words: 4,
    created_by: "44444444-4444-4444-8444-444444444444",
    created_at: "2026-11-22T10:00:00Z",
    ...changes,
  };
}

const form = (over: Record<string, string> = {}) => {
  const data = new FormData();
  const fields = {
    goal: "after_visit",
    language: "hi",
    tone: "brisk",
    length: "30",
    quote_id: "",
    lines: "Hello\nThanks",
    ...over,
  };
  for (const [k, v] of Object.entries(fields)) data.set(k, v);
  return data;
};

describe("the helpers", () => {
  it("accepts only values inside the fixed lists and needs a language", () => {
    expect(
      strictChoices({
        goal: "revive",
        language: "te",
        tone: "warm",
        length: "90",
        quote_id: "",
      }),
    ).toEqual({
      goal: "revive",
      language: "te",
      tone: "warm",
      length: 90,
      quoteId: "",
    });
    for (const over of [
      { goal: "spam" },
      { language: "fr" },
      { language: "" },
      { tone: "angry" },
      { length: "45" },
    ])
      expect(
        strictChoices({
          goal: "follow_up",
          language: "en",
          tone: "warm",
          length: "60",
          quote_id: "",
          ...over,
        }),
      ).toBeNull();
  });

  it("explains each refusal of a draft in plain words", () => {
    for (const code of [
      "agent_unavailable",
      "agent_budget_reached",
      "video_draft_rate_limited",
      "video_draft_invalid_answer",
      "video_draft_unsupported_number",
      "video_draft_assumption_stated",
      "video_draft_script_banned_phrase",
      "video_draft_script_contact_detail",
      "video_draft_script_unsafe_text",
      "quote_not_found",
      "video_brief_quote_not_ready",
    ])
      expect(scriptErrorText(code, "fallback")).not.toBe("fallback");
    expect(scriptErrorText("agent_unavailable", "x")).toMatch(/switched off/);
    expect(scriptErrorText("video_draft_unsupported_number", "x")).toMatch(
      /number/,
    );
  });
});

describe("drafting", () => {
  it("sends only the choices, never the lines, and returns the draft", async () => {
    apiFetch.mockReset();
    apiFetch.mockResolvedValue({
      status: "draft",
      lines: ["Hello Suresh,", "Thank you."],
      words: 4,
      reason: "From the facts.",
    });
    const data = form({ quote_id: QUOTE });
    data.set("tenant_id", "x");
    const state = await draftVideoScript(LEAD, initialDraftState, data);
    expect(apiFetch.mock.calls[0][0]).toBe(`/leads/${LEAD}/video-brief/draft`);
    expect(JSON.parse(apiFetch.mock.calls[0][1].body)).toEqual({
      goal: "after_visit",
      language: "hi",
      tone: "brisk",
      length_seconds: 30,
      quote_id: QUOTE,
    });
    expect(state.draft).toEqual({
      lines: ["Hello Suresh,", "Thank you."],
      words: 4,
      reason: "From the facts.",
    });
    expect(state.attempt).toBe(1);
  });

  it("leaves the quote out when none was chosen and refuses a tampered lead id", async () => {
    apiFetch.mockReset();
    apiFetch.mockResolvedValue({ lines: ["a"], words: 1, reason: "r" });
    await draftVideoScript(LEAD, initialDraftState, form());
    expect(JSON.parse(apiFetch.mock.calls[0][1].body)).not.toHaveProperty(
      "quote_id",
    );
    apiFetch.mockReset();
    await expect(
      draftVideoScript("../x", initialDraftState, form()),
    ).rejects.toThrow("invalid lead");
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("does not call the API when a choice is outside the lists", async () => {
    apiFetch.mockReset();
    const state = await draftVideoScript(
      LEAD,
      initialDraftState,
      form({ tone: "angry" }),
    );
    expect(state.error).not.toBeNull();
    expect(state.draft).toBeNull();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("explains an off drafter or a thrown-away draft and keeps no draft", async () => {
    apiFetch.mockReset();
    apiFetch.mockRejectedValue(problem(503, "agent_unavailable"));
    let state = await draftVideoScript(LEAD, initialDraftState, form());
    expect(state.error?.message).toMatch(/switched off/);
    expect(state.draft).toBeNull();
    apiFetch.mockRejectedValue(problem(422, "video_draft_unsupported_number"));
    state = await draftVideoScript(LEAD, state, form());
    expect(state.error?.message).toMatch(/number/);
    expect(state.attempt).toBe(2);
  });
});

describe("sending for approval", () => {
  it("sends only the documented fields and goes back with the proposal", async () => {
    apiFetch.mockReset();
    apiFetch.mockResolvedValue({
      outcome: "proposed",
      proposal_id: PROPOSAL,
      proposal_link: `/approvals/${PROPOSAL}`,
      blocked_message: null,
    });
    const data = form({ quote_id: QUOTE });
    data.set("version", "9");
    data.set("agent", "staff_assistant");
    await expect(
      proposeVideoScript(LEAD, initialDialogState, data),
    ).rejects.toThrow(
      `REDIRECT:/print/leads/${LEAD}/video-brief?goal=after_visit&tone=brisk&length=30&language=hi&quote_id=${QUOTE}&proposed=${PROPOSAL}`,
    );
    expect(apiFetch.mock.calls[0][0]).toBe(
      `/leads/${LEAD}/video-brief/propose`,
    );
    expect(JSON.parse(apiFetch.mock.calls[0][1].body)).toEqual({
      goal: "after_visit",
      language: "hi",
      tone: "brisk",
      length_seconds: 30,
      lines: ["Hello", "Thanks"],
      quote_id: QUOTE,
    });
  });

  it("checks the script and the lead before calling the API", async () => {
    apiFetch.mockReset();
    const empty = await proposeVideoScript(
      LEAD,
      initialDialogState,
      form({ lines: "  " }),
    );
    expect(empty.fieldErrors.lines).toBeTruthy();
    await expect(
      proposeVideoScript("../x", initialDialogState, form()),
    ).rejects.toThrow("invalid lead");
    const bad = await proposeVideoScript(
      LEAD,
      initialDialogState,
      form({ goal: "spam" }),
    );
    expect(bad.error).not.toBeNull();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("shows the safety check's refusal and does not go anywhere", async () => {
    apiFetch.mockReset();
    apiFetch.mockResolvedValue({
      outcome: "blocked",
      proposal_id: null,
      proposal_link: null,
      blocked_message: "A line contains a link.",
    });
    const state = await proposeVideoScript(LEAD, initialDialogState, form());
    expect(state.error?.message).toBe("A line contains a link.");
  });

  it("explains a script the server's checks refused", async () => {
    apiFetch.mockReset();
    apiFetch.mockRejectedValue(problem(422, "video_draft_assumption_stated"));
    const state = await proposeVideoScript(LEAD, initialDialogState, form());
    expect(state.error?.message).toMatch(/guess|assumption/i);
  });
});

describe("the editor with the draft button", () => {
  const save = vi.fn();
  const propose = vi.fn();
  const draftReturning = (state: Partial<DraftState>) =>
    vi.fn(async (_id: string, previous: DraftState) => ({
      ...previous,
      attempt: previous.attempt + 1,
      ...state,
    }));

  it("has three buttons and no draft note at first", () => {
    render(
      <VideoScriptEditor
        leadId={LEAD}
        brief={brief()}
        action={save}
        draftAction={draftReturning({})}
        proposeAction={propose}
        initialText="Hello"
      />,
    );
    for (const name of ["Save script", "Draft with AI", "Send for approval"])
      expect(screen.getByRole("button", { name })).toBeVisible();
    expect(screen.queryByText(/not saved and not approved/i)).toBeNull();
  });

  it("puts the draft in the box and says it is neither saved nor approved", async () => {
    const draft = draftReturning({
      draft: {
        lines: ["Hello Suresh,", "On Budget, you told us: Up to 1.5 Cr."],
        words: 11,
        reason: "From the confirmed facts.",
      },
    });
    render(
      <VideoScriptEditor
        leadId={LEAD}
        brief={brief()}
        action={save}
        draftAction={draft}
        proposeAction={propose}
        initialText="Old text"
      />,
    );
    await act(async () => {
      await userEvent.click(
        screen.getByRole("button", { name: "Draft with AI" }),
      );
    });
    expect(screen.getByLabelText(/Your script/)).toHaveValue(
      "Hello Suresh,\nOn Budget, you told us: Up to 1.5 Cr.",
    );
    expect(screen.getByText(/not saved and not approved/i)).toBeVisible();
    expect(screen.getByText(/From the confirmed facts\./)).toBeVisible();
  });

  it("keeps the typed text when the draft is refused and shows why", async () => {
    const draft = draftReturning({
      error: {
        status: 503,
        message: "The drafter is switched off.",
        code: "agent_unavailable",
        requestId: null,
        fieldErrors: {},
      },
    });
    render(
      <VideoScriptEditor
        leadId={LEAD}
        brief={brief()}
        action={save}
        draftAction={draft}
        proposeAction={propose}
        initialText="Hello"
      />,
    );
    const box = screen.getByLabelText(/Your script/);
    await userEvent.clear(box);
    await userEvent.type(box, "My own words");
    await act(async () => {
      await userEvent.click(
        screen.getByRole("button", { name: "Draft with AI" }),
      );
    });
    expect(screen.getByText("The drafter is switched off.")).toBeVisible();
    expect(screen.getByLabelText(/Your script/)).toHaveValue("My own words");
  });

  it("sends what is in the box for approval, as the person left it", async () => {
    const send = vi.fn(async (_id: string, previous, formData: FormData) => {
      void formData;
      return { ...previous, attempt: previous.attempt + 1 };
    });
    render(
      <VideoScriptEditor
        leadId={LEAD}
        brief={brief({ language: "te", length_seconds: 90 })}
        action={save}
        draftAction={draftReturning({})}
        proposeAction={send}
        initialText="Hello"
        quoteId={QUOTE}
      />,
    );
    const box = screen.getByLabelText(/Your script/);
    await userEvent.clear(box);
    await userEvent.type(box, "Edited line");
    await act(async () => {
      await userEvent.click(
        screen.getByRole("button", { name: "Send for approval" }),
      );
    });
    expect(send).toHaveBeenCalledTimes(1);
    const data = send.mock.calls[0][2];
    expect(data.get("lines")).toBe("Edited line");
    expect(data.get("language")).toBe("te");
    expect(data.get("length")).toBe("90");
    expect(data.get("quote_id")).toBe(QUOTE);
    expect(save).not.toHaveBeenCalled();
  });
});

describe("the saved scripts say where each came from", () => {
  it("labels hand-written and approved AI drafts", () => {
    render(
      <SavedScripts
        scripts={[
          saved({ version: 2, source: "ai_draft" }),
          saved({ version: 1, source: "hand_written" }),
        ]}
      />,
    );
    const items = screen.getAllByRole("listitem", { name: /Version/ });
    expect(items[0]).toHaveTextContent("AI draft, approved by a colleague");
    expect(items[1]).toHaveTextContent("Written by hand");
  });
});

describe("the page after sending", () => {
  const show = async (sp: Record<string, string> = {}) =>
    render(
      await VideoBriefPage({
        params: Promise.resolve({ id: LEAD }),
        searchParams: Promise.resolve(sp),
      } as never),
    );
  const answers = () => {
    apiFetch.mockReset();
    apiFetch.mockImplementation(async (path: string) => {
      if (path === `/leads/${LEAD}`) return { converted_account_id: null };
      if (path.includes("/video-scripts")) return { items: [] };
      return brief();
    });
    getMe.mockResolvedValue({ permissions: ["video_brief:write"] });
  };

  it("says the script waits for a colleague and links to the proposal", async () => {
    answers();
    await show({ proposed: PROPOSAL });
    const note = screen.getByRole("status");
    expect(note).toHaveTextContent(/waits for a colleague/i);
    expect(screen.getByRole("link", { name: /approval/i })).toHaveAttribute(
      "href",
      `/approvals/${PROPOSAL}`,
    );
  });

  it("ignores a proposal id that is not an id", async () => {
    answers();
    await show({ proposed: "<script>" });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("offers the draft and send buttons only to people who may write", async () => {
    answers();
    await show();
    expect(screen.getByRole("button", { name: "Draft with AI" })).toBeVisible();
    getMe.mockResolvedValue({ permissions: ["video_brief:read"] });
    document.body.innerHTML = "";
    await show();
    expect(screen.queryByRole("button", { name: "Draft with AI" })).toBeNull();
  });
});

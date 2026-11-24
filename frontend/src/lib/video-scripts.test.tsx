import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { agentLabel } from "@/components/approval-views";
import { describeChange } from "@/lib/approvals";
import { saveVideoScript } from "@/app/print/leads/[id]/video-brief/actions";
import VideoBriefPage from "@/app/print/leads/[id]/video-brief/page";
import { SavedScripts } from "@/components/saved-scripts";
import { VideoScriptEditor } from "@/components/video-script-editor";
import { ApiError } from "@/lib/api-error";
import type { ScriptRead, VideoBrief } from "@/lib/api-types";
import { initialDialogState } from "@/lib/dialog-state";
import { canWriteVideoBrief } from "@/lib/permissions";
import {
  checkScript,
  countWords,
  scriptErrorText,
  splitLines,
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
    version: 2,
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

describe("the helpers", () => {
  it("splits text into trimmed, non-empty lines", () => {
    expect(splitLines("  Hello  \n\n  World  \r\n")).toEqual([
      "Hello",
      "World",
    ]);
    expect(splitLines("  \n ")).toEqual([]);
  });

  it("counts words", () => {
    expect(countWords("a  b\nc")).toBe(3);
    expect(countWords("   ")).toBe(0);
  });

  it("accepts a fitting script and shapes the body", () => {
    expect(checkScript("Hello Suresh,\nThank you.", 60)).toEqual({
      ok: true,
      lines: ["Hello Suresh,", "Thank you."],
    });
  });

  it("refuses an empty script, too many lines, a long line and too many words", () => {
    expect(checkScript("  ", 60)).toMatchObject({ ok: false });
    expect(
      checkScript(
        Array.from({ length: 13 }, (_, i) => `Line ${i}`).join("\n"),
        90,
      ),
    ).toMatchObject({ ok: false });
    expect(checkScript("a".repeat(301), 90)).toMatchObject({ ok: false });
    const long = Array.from({ length: 8 }, (_, j) =>
      Array.from({ length: 10 }, (_, i) => `w${j * 10 + i}`).join(" "),
    ).join("\n"); // 80 words on 8 lines
    const tooLong = checkScript(long, 30);
    expect(tooLong).toMatchObject({ ok: false });
    expect(tooLong.ok === false && tooLong.fieldErrors.lines).toMatch(
      /80 words.*30 seconds.*75/,
    );
    expect(checkScript(long, 60).ok).toBe(true);
  });

  it("explains each refusal in plain words", () => {
    // A too-long script keeps the server's sentence, which carries the counts.
    expect(scriptErrorText("script_too_long", "fallback")).toBe("fallback");
    for (const code of [
      "script_empty",
      "script_too_many_lines",
      "script_line_too_long",
      "script_unsafe_text",
      "script_contact_detail",
      "script_banned_phrase",
      "video_script_rate_limited",
    ])
      expect(scriptErrorText(code, "fallback")).not.toBe("fallback");
    expect(scriptErrorText("other", "fallback")).toBe("fallback");
    expect(scriptErrorText(null, "fallback")).toBe("fallback");
  });

  it("shows the save form only to people who may write video briefs", () => {
    expect(canWriteVideoBrief({ permissions: ["video_brief:write"] })).toBe(
      true,
    );
    expect(canWriteVideoBrief({ permissions: ["video_brief:read"] })).toBe(
      false,
    );
  });
});

describe("the Server Action", () => {
  const form = (over: Record<string, string> = {}) => {
    const data = new FormData();
    const fields = {
      goal: "after_visit",
      language: "hi",
      tone: "brisk",
      length: "30",
      lines: "Hello\nThanks",
      ...over,
    };
    for (const [k, v] of Object.entries(fields)) data.set(k, v);
    return data;
  };

  it("sends only the five fields the API accepts, then goes back with the version", async () => {
    apiFetch.mockReset();
    apiFetch.mockResolvedValue(saved({ version: 3 }));
    const data = form();
    data.set("tenant_id", "x");
    data.set("version", "9");
    data.set("source", "ai_draft");
    await expect(
      saveVideoScript(LEAD, initialDialogState, data),
    ).rejects.toThrow(
      `REDIRECT:/print/leads/${LEAD}/video-brief?goal=after_visit&tone=brisk&length=30&language=hi&saved=3`,
    );
    expect(apiFetch.mock.calls[0][0]).toBe(`/leads/${LEAD}/video-scripts`);
    expect(JSON.parse(apiFetch.mock.calls[0][1].body)).toEqual({
      language: "hi",
      tone: "brisk",
      goal: "after_visit",
      length_seconds: 30,
      lines: ["Hello", "Thanks"],
    });
  });

  it("refuses a tampered lead id before calling the API", async () => {
    apiFetch.mockReset();
    await expect(
      saveVideoScript("../x", initialDialogState, form()),
    ).rejects.toThrow("invalid lead");
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("checks the script first and does not call the API for an empty one", async () => {
    apiFetch.mockReset();
    const state = await saveVideoScript(
      LEAD,
      initialDialogState,
      form({ lines: "  " }),
    );
    expect(state.attempt).toBe(1);
    expect(state.fieldErrors.lines).toBeTruthy();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("does not call the API when a choice is outside the fixed lists", async () => {
    apiFetch.mockReset();
    const overs: Record<string, string>[] = [
      { language: "fr" },
      { language: "" },
      { tone: "angry" },
      { goal: "spam" },
      { length: "45" },
    ];
    for (const over of overs) {
      const state = await saveVideoScript(LEAD, initialDialogState, form(over));
      expect(state.error ?? state.fieldErrors).toBeTruthy();
    }
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("explains a refusal of the API in plain words and keeps the attempt count", async () => {
    apiFetch.mockReset();
    apiFetch.mockRejectedValue(problem(422, "script_banned_phrase"));
    const state = await saveVideoScript(LEAD, initialDialogState, form());
    expect(state.attempt).toBe(1);
    expect(state.error?.message).toMatch(/never-say list/i);
  });
});

describe("the editor", () => {
  const action = vi.fn();

  it("starts from the suggested script and counts words against the length", () => {
    render(
      <VideoScriptEditor
        leadId={LEAD}
        brief={brief()}
        action={action}
        initialText={"Hello Suresh,\nThank you."}
      />,
    );
    const box = screen.getByLabelText(/Your script/);
    expect(box).toHaveValue("Hello Suresh,\nThank you.");
    expect(
      screen.getByText(/4 words; 60 seconds holds about 150/),
    ).toBeVisible();
  });

  it("sends the brief's resolved choices as hidden fields, not editable ones", () => {
    const { container } = render(
      <VideoScriptEditor
        leadId={LEAD}
        brief={brief({ language: "te", length_seconds: 90, goal: "revive" })}
        action={action}
        initialText="x"
      />,
    );
    const hidden = (name: string) =>
      (container.querySelector(`input[name="${name}"]`) as HTMLInputElement)
        .value;
    expect(hidden("language")).toBe("te");
    expect(hidden("length")).toBe("90");
    expect(hidden("goal")).toBe("revive");
    expect(hidden("tone")).toBe("warm");
  });

  it("updates the count as the person types and marks too many words", async () => {
    render(
      <VideoScriptEditor
        leadId={LEAD}
        brief={brief({ length_seconds: 30, word_target: 75 })}
        action={action}
        initialText=""
      />,
    );
    const box = screen.getByLabelText(/Your script/);
    await userEvent.click(box);
    await userEvent.paste(
      Array.from({ length: 80 }, (_, i) => `w${i}`).join(" "),
    );
    expect(screen.getByText(/80 words; 30 seconds holds about 75/)).toHaveClass(
      "text-red-700",
    );
  });

  it("shows an error from the action and keeps what was typed", async () => {
    const failing = vi.fn(async () => ({
      attempt: 1,
      fieldErrors: {},
      error: {
        status: 422,
        message: "Take out the card number.",
        code: "script_unsafe_text",
        requestId: null,
        fieldErrors: {},
      },
    }));
    render(
      <VideoScriptEditor
        leadId={LEAD}
        brief={brief()}
        action={failing}
        initialText="Hello"
      />,
    );
    const box = screen.getByLabelText(/Your script/);
    await userEvent.clear(box);
    await userEvent.type(box, "My own words");
    await act(async () => {
      await userEvent.click(
        screen.getByRole("button", { name: "Save script" }),
      );
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Take out the card number.",
    );
    expect(screen.getByLabelText(/Your script/)).toHaveValue("My own words");
  });
});

describe("the saved scripts", () => {
  it("lists versions newest first as plain text with who and when", () => {
    render(
      <SavedScripts
        scripts={[
          saved({ version: 2 }),
          saved({ version: 1, lines: ["Older line."], language: "hi" }),
        ]}
      />,
    );
    const region = screen.getByRole("region", { name: "Saved scripts" });
    const items = within(region).getAllByRole("listitem", { name: /Version/ });
    expect(items[0]).toHaveTextContent("Version 2");
    expect(items[1]).toHaveTextContent("Version 1");
    expect(items[1]).toHaveTextContent("Hindi");
    expect(items[1]).toHaveTextContent("Older line.");
  });

  it("shows nothing but a sentence when none is saved, and never markup", () => {
    const { container, rerender } = render(<SavedScripts scripts={[]} />);
    expect(screen.getByText(/No script saved yet/)).toBeInTheDocument();
    rerender(
      <SavedScripts
        scripts={[saved({ lines: ['<img src=x onerror="a()"> hi'] })]}
      />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<img src=x");
  });
});

describe("the page", () => {
  const show = async (sp: Record<string, string> = {}) =>
    render(
      await VideoBriefPage({
        params: Promise.resolve({ id: LEAD }),
        searchParams: Promise.resolve(sp),
      } as never),
    );
  const answers = (scripts: ScriptRead[] | Error) => {
    apiFetch.mockReset();
    apiFetch.mockImplementation(async (path: string) => {
      if (path === `/leads/${LEAD}`) return { converted_account_id: null };
      if (path.includes("/video-scripts")) {
        if (scripts instanceof Error) throw scripts;
        return { items: scripts };
      }
      return brief();
    });
  };

  it("offers the editor and the saved scripts to a person who may write", async () => {
    getMe.mockResolvedValue({ permissions: ["video_brief:write"] });
    answers([saved()]);
    await show();
    expect(screen.getByLabelText(/Your script/)).toHaveValue(
      "Hello Suresh,\nThank you.",
    );
    expect(
      screen.getByRole("region", { name: "Saved scripts" }),
    ).toHaveTextContent("Version 2");
  });

  it("says a script was saved after the redirect", async () => {
    getMe.mockResolvedValue({ permissions: ["video_brief:write"] });
    answers([saved({ version: 3 })]);
    await show({ saved: "3" });
    expect(screen.getByRole("status")).toHaveTextContent(/version 3/i);
  });

  it("hides the editor from a person who may only read, but still shows saved scripts", async () => {
    getMe.mockResolvedValue({ permissions: ["video_brief:read"] });
    answers([saved()]);
    await show();
    expect(screen.queryByLabelText(/Your script/)).toBeNull();
    expect(screen.getByRole("region", { name: "Saved scripts" })).toBeVisible();
  });

  it("still shows the brief when the saved scripts cannot be loaded", async () => {
    getMe.mockResolvedValue({ permissions: ["video_brief:write"] });
    answers(problem(500, "boom"));
    await show();
    expect(screen.getByRole("region", { name: "The script" })).toBeVisible();
    expect(screen.queryByRole("region", { name: "Saved scripts" })).toBeNull();
  });

  it("ignores a made-up saved number", async () => {
    getMe.mockResolvedValue({ permissions: ["video_brief:write"] });
    answers([]);
    await show({ saved: "<script>" });
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("the approval card for a drafted script", () => {
  it("names the video script drafter", () => {
    expect(agentLabel({ agent: "video_brief", custom_agent_name: null })).toBe(
      "the video script drafter",
    );
  });

  it("shows the planned change as the script's lines, and 'no saved script' before", () => {
    const text = describeChange(
      {
        field: "video_script",
        before: null,
        after: ["Hello Suresh,", "Thank you."],
      },
      () => "x",
    );
    expect(text).toBe(
      "Video script: no saved script → Hello Suresh, / Thank you.",
    );
    expect(
      describeChange(
        { field: "video_script", before: ["Old."], after: ["New."] },
        () => "x",
      ),
    ).toBe("Video script: Old. → New.");
  });
});

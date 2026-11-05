import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AnswerView } from "@/components/knowledge-ask";
import type { KnowledgeAnswerResponse } from "@/lib/api-types";
import { LIVE_CHECK_LINE, refusalHint, splitLiveCheck } from "@/lib/knowledge";

/**
 * How the knowledge answer shows the RERA / price refusal gate (CRM-115 / BP-08, step BR4,
 * docs/brochures-rera.md). The API decides; the screen only puts its codes into plain words.
 */

function answer(
  overrides: Partial<KnowledgeAnswerResponse> = {},
): KnowledgeAnswerResponse {
  return {
    query_id: null,
    answer: "Skyline Towers starts at ₹78 lakh [1].",
    sources: [
      {
        chunk_id: "c1",
        document_id: "d1",
        document_title: "Skyline Towers brochure",
        heading_path: "Homes and prices",
        page_from: null,
        page_to: null,
        text: "2 BHK: from ₹78 lakh.",
      },
    ],
    exact_chunk_id: "c1",
    enough: true,
    model_used: true,
    grounded: true,
    citations: [1],
    refusal_reason: null,
    ...overrides,
  };
}

describe("refusal hints", () => {
  it("say why each refusal happened, in plain words", () => {
    expect(refusalHint("not_found")).toMatch(/close enough/);
    expect(refusalHint("ungrounded")).toMatch(/not fully supported/);
    expect(refusalHint("rera_not_found")).toMatch(/RERA number/);
    expect(refusalHint("rera_not_found")).toMatch(/check the number/i);
    expect(refusalHint("rera_not_cited")).toMatch(/RERA number/);
    expect(refusalHint("price_not_cited")).toMatch(/price/);
  });
  it("say nothing for an answer and a sensible thing for a new code", () => {
    expect(refusalHint(null)).toBeNull();
    expect(refusalHint("something_new")).toMatch(/could not be answered/);
  });
});

describe("the fixed 'not a live check' line", () => {
  it("is split off the answer when it is there", () => {
    expect(
      splitLiveCheck(
        `Its number is DEMO-P02400000003 [1].\n\n${LIVE_CHECK_LINE}`,
      ),
    ).toEqual({
      text: "Its number is DEMO-P02400000003 [1].",
      liveCheck: true,
    });
  });
  it("leaves an answer without it alone", () => {
    expect(splitLiveCheck("From ₹78 lakh [1].")).toEqual({
      text: "From ₹78 lakh [1].",
      liveCheck: false,
    });
  });
  it("is only recognised at the very end", () => {
    const text = `${LIVE_CHECK_LINE} And more.`;
    expect(splitLiveCheck(text)).toEqual({ text, liveCheck: false });
  });
});

describe("AnswerView", () => {
  it("shows a good answer without any refusal hint", () => {
    render(<AnswerView answer={answer()} />);
    expect(
      screen.getByText("Skyline Towers starts at ₹78 lakh [1]."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/close enough/)).not.toBeInTheDocument();
  });

  it("shows the fixed line as its own note, not inside the answer", () => {
    render(
      <AnswerView
        answer={answer({
          answer: `Skyline is DEMO-P02400000003 [1].\n\n${LIVE_CHECK_LINE}`,
        })}
      />,
    );
    expect(
      screen.getByText("Skyline is DEMO-P02400000003 [1]."),
    ).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent(LIVE_CHECK_LINE);
  });

  it("explains an unknown RERA number instead of 'nothing close enough'", () => {
    render(
      <AnswerView
        answer={answer({
          answer:
            "I couldn't find RERA number DEMO-P02499999999 in the documents I can see.",
          sources: [],
          enough: false,
          model_used: false,
          grounded: false,
          citations: [],
          refusal_reason: "rera_not_found",
        })}
      />,
    );
    expect(screen.getByText(/check the number/i)).toBeInTheDocument();
    expect(screen.queryByText(/close enough/)).not.toBeInTheDocument();
    expect(screen.queryByText("Sources used")).not.toBeInTheDocument();
  });

  it("explains an answer that quoted a price the documents do not contain", () => {
    render(
      <AnswerView
        answer={answer({
          answer:
            "I couldn't produce an answer whose RERA numbers and prices all come from the cited documents.",
          sources: [],
          enough: false,
          grounded: false,
          citations: [],
          refusal_reason: "price_not_cited",
        })}
      />,
    );
    expect(
      screen.getByText(/price/, { selector: "p.mt-2" }),
    ).toBeInTheDocument();
  });

  it("keeps the old hint for nothing close enough", () => {
    render(
      <AnswerView
        answer={answer({
          answer:
            "I couldn't find enough information in the knowledge base to answer that.",
          sources: [],
          enough: false,
          model_used: false,
          grounded: false,
          citations: [],
          refusal_reason: "not_found",
        })}
      />,
    );
    expect(screen.getByText(/close enough/)).toBeInTheDocument();
  });
});

import { describe, expect, it } from "vitest";

import type { KnowledgeSearchHit } from "@/lib/api-types";
import { citationLabel, excerpt, matchLabel } from "@/lib/knowledge";

function hit(overrides: Partial<KnowledgeSearchHit> = {}): KnowledgeSearchHit {
  return {
    chunk_id: "c",
    document_id: "d",
    document_title: "Returns policy",
    file_name: "returns.md",
    heading_path: "Damaged items",
    page_from: 2,
    page_to: 2,
    text: "Damaged items may be returned within 14 days.",
    blocks: [],
    visibility: "internal",
    similarity: 0.9,
    keyword_rank: 2,
    score: 0.02,
    rerank_score: 7.5,
    ...overrides,
  };
}

describe("knowledge result formatting", () => {
  it("collapses whitespace and truncates long passages", () => {
    expect(excerpt("  a\n\n b   c ")).toBe("a b c");
    expect(excerpt("x".repeat(30), 10)).toBe("xxxxxxxxx…");
  });

  it("labels a citation with heading and page range", () => {
    expect(citationLabel(hit())).toBe("Returns policy · Damaged items · p. 2");
    expect(citationLabel(hit({ page_from: 2, page_to: 3 }))).toContain("p. 2-3");
    expect(citationLabel(hit({ page_from: null, heading_path: "" }))).toBe(
      "Returns policy",
    );
  });

  it("explains why a passage matched", () => {
    expect(matchLabel(hit())).toEqual(["Reranked", "Meaning 90%", "Keyword #2"]);
    expect(
      matchLabel(hit({ rerank_score: null, keyword_rank: null })),
    ).toEqual(["Meaning 90%"]);
  });
});

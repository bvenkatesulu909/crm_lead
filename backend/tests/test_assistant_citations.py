"""Assistant citations are extracted only from the help-search tool result."""

import json

from app.modules.assistant.service import citations_from_tool_result


def test_citations_are_extracted_and_deduplicated():
    content = json.dumps(
        {
            "articles": [
                {"document": "Returns policy", "heading": "Damaged", "page": 1, "text": "x"},
                {"document": "Returns policy", "heading": "Damaged", "page": 1, "text": "x"},
                {"document": "Delivery", "heading": "Tracking", "page": None},
            ]
        }
    )
    assert citations_from_tool_result(content) == [
        {"document": "Returns policy", "heading": "Damaged", "page": 1},
        {"document": "Delivery", "heading": "Tracking", "page": None},
    ]


def test_bad_tool_content_yields_no_citations():
    assert citations_from_tool_result("not json") == []
    assert citations_from_tool_result("{}") == []

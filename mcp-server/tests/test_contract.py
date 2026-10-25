"""The tool contract (ADR 0015, D2): catalogue, rules and version rule."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from crm_mcp import catalogue as c

LIVE = c.current_catalogue()


def tool(
    name: str = "get_thing", props: dict[str, Any] | None = None, required: list[str] | None = None
) -> dict[str, Any]:
    return {
        "name": name,
        "description": "Gets a thing.",
        "input_schema": {"type": "object", "properties": props or {}, "required": required or []},
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        "endpoints": ["GET /things"],
    }


def cat(*tools: dict[str, Any], version: str = "0.1.0") -> dict[str, Any]:
    return {"version": version, "tools": list(tools)}


# --- the real server matches what is written down ---------------------------------------------


def test_the_committed_catalogue_matches_the_live_server() -> None:
    committed = json.loads(c.SNAPSHOT.read_text(encoding="utf-8"))
    assert committed == LIVE, "run `uv run python -m crm_mcp.catalogue --write`"


def test_the_document_matches_the_live_server() -> None:
    text = c.DOC.read_text(encoding="utf-8")
    assert c.render_doc(text, LIVE) == text, "run `uv run python -m crm_mcp.catalogue --write`"


def test_the_live_tools_follow_the_rules() -> None:
    assert c.rule_violations(LIVE) == []


def test_there_are_tools_and_they_are_all_read_only() -> None:
    assert len(LIVE["tools"]) >= 8
    assert all(t["annotations"]["readOnlyHint"] is True for t in LIVE["tools"])


def test_the_version_is_the_package_version() -> None:
    assert LIVE["version"] == c.contract_version()


def test_the_check_command_reports_in_sync(capsys: pytest.CaptureFixture[str]) -> None:
    assert c.main([]) == 0
    assert "In sync" in capsys.readouterr().out


# --- what counts as a breaking change ---------------------------------------------------------


def test_identical_catalogues_have_no_change() -> None:
    assert c.classify_change(cat(tool()), cat(tool())) == "none"


def test_removing_or_renaming_a_tool_is_breaking() -> None:
    assert c.classify_change(cat(tool()), cat()) == "breaking"
    assert c.classify_change(cat(tool()), cat(tool("get_other"))) == "breaking"


def test_adding_a_tool_is_compatible() -> None:
    assert c.classify_change(cat(tool()), cat(tool(), tool("get_other"))) == "compatible"


def test_removing_an_input_is_breaking() -> None:
    old = cat(tool(props={"q": {"type": "string"}}))
    assert c.classify_change(old, cat(tool())) == "breaking"


def test_an_optional_input_is_compatible_a_required_one_is_breaking() -> None:
    new_prop = {"q": {"type": "string"}}
    assert c.classify_change(cat(tool()), cat(tool(props=new_prop))) == "compatible"
    assert c.classify_change(cat(tool()), cat(tool(props=new_prop, required=["q"]))) == "breaking"


def test_an_optional_input_becoming_required_is_breaking() -> None:
    props = {"q": {"type": "string"}}
    old, new = cat(tool(props=props)), cat(tool(props=props, required=["q"]))
    assert c.classify_change(old, new) == "breaking"


def test_allowed_values_may_grow_but_not_shrink() -> None:
    def with_values(*values: str) -> dict[str, Any]:
        return cat(tool(props={"s": {"type": "string", "enum": list(values)}}))

    assert c.classify_change(with_values("a", "b"), with_values("a", "b", "c")) == "compatible"
    assert c.classify_change(with_values("a", "b"), with_values("a")) == "breaking"
    plain = cat(tool(props={"s": {"type": "string"}}))
    assert c.classify_change(plain, with_values("a")) == "breaking"


def test_values_inside_an_array_input_count_too() -> None:
    def listed(*values: str) -> dict[str, Any]:
        item = {"type": "array", "items": {"type": "string", "enum": list(values)}}
        return cat(tool(props={"s": {"anyOf": [item, {"type": "null"}]}}))

    assert c.classify_change(listed("a", "b"), listed("a")) == "breaking"


def test_a_narrower_type_is_breaking() -> None:
    old = cat(tool(props={"n": {"anyOf": [{"type": "integer"}, {"type": "string"}]}}))
    new = cat(tool(props={"n": {"type": "integer"}}))
    assert c.classify_change(old, new) == "breaking"


def test_a_tool_that_stops_being_read_only_is_breaking() -> None:
    changed = tool()
    changed["annotations"] = {**changed["annotations"], "readOnlyHint": False}
    assert c.classify_change(cat(tool()), cat(changed)) == "breaking"


def test_a_new_description_is_only_wording() -> None:
    changed = tool()
    changed["description"] = "Fetches a thing."
    assert c.classify_change(cat(tool()), cat(changed)) == "wording"


# --- the version rule -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "old", "new", "allowed"),
    [
        ("none", "0.1.0", "0.1.0", True),
        ("wording", "0.1.0", "0.1.0", True),
        ("compatible", "0.1.0", "0.1.0", False),
        ("compatible", "0.1.0", "0.1.1", True),  # before 1.0 a compatible change is a patch
        ("breaking", "0.1.0", "0.1.1", False),
        ("breaking", "0.1.0", "0.2.0", True),
        ("compatible", "1.2.0", "1.2.1", False),
        ("compatible", "1.2.0", "1.3.0", True),
        ("breaking", "1.2.0", "1.3.0", False),
        ("breaking", "1.2.0", "2.0.0", True),
        ("none", "0.2.0", "0.1.0", False),  # versions never go down
    ],
)
def test_the_version_bump_must_cover_the_change(
    change: str, old: str, new: str, allowed: bool
) -> None:
    assert c.bump_allows(change, old, new) is allowed  # type: ignore[arg-type]


def test_a_malformed_version_is_refused() -> None:
    with pytest.raises(ValueError, match="major.minor.patch"):
        c.bump_allows("none", "1.0", "1.0.1")


# --- the rules every tool follows -------------------------------------------------------------


def test_a_badly_named_tool_is_reported() -> None:
    assert any("name must be" in p for p in c.rule_violations(cat(tool("delete_everything"))))


def test_a_tool_that_may_write_is_reported() -> None:
    writer = tool()
    writer["annotations"] = {**writer["annotations"], "readOnlyHint": False}
    assert any("read-only" in p for p in c.rule_violations(cat(writer)))


def test_a_tool_without_description_or_endpoints_is_reported() -> None:
    bare = tool()
    bare["description"], bare["endpoints"] = " ", []
    problems = c.rule_violations(cat(bare))
    assert any("description" in p for p in problems) and any("endpoints" in p for p in problems)


def test_a_page_size_above_the_cap_is_reported() -> None:
    big = tool(props={"limit": {"type": "integer", "default": 500}})
    assert any("page size" in p for p in c.rule_violations(cat(big)))


def test_an_endpoint_entry_for_a_missing_tool_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(c.ENDPOINTS, "get_ghost", ("GET /ghosts",))
    assert any("get_ghost" in p for p in c.rule_violations(LIVE))


# --- writing the files ------------------------------------------------------------------------


def test_the_document_needs_its_generated_block() -> None:
    with pytest.raises(ValueError, match="no generated catalogue block"):
        c.render_doc("# nothing here", LIVE)


def test_write_refuses_a_change_without_a_big_enough_version_bump(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    snapshot, doc = tmp_path / "catalogue.json", tmp_path / "mcp-tools.md"
    snapshot.write_text(c.dump(LIVE), encoding="utf-8")
    doc.write_text(f"{c.BEGIN}\nold\n{c.END}\n", encoding="utf-8")
    removed = copy.deepcopy(LIVE)
    first = removed["tools"][0]["name"]
    removed["tools"] = removed["tools"][1:]  # a tool disappears, version unchanged
    monkeypatch.setattr(c, "SNAPSHOT", snapshot)
    monkeypatch.setattr(c, "DOC", doc)
    monkeypatch.setattr(c, "current_catalogue", lambda: removed)
    monkeypatch.delitem(c.ENDPOINTS, first)  # the removed tool has no endpoints either
    assert c.main(["--write"]) == 1
    assert "breaking change needs a higher version" in capsys.readouterr().out
    assert json.loads(snapshot.read_text(encoding="utf-8")) == LIVE  # nothing was overwritten
    removed["version"] = "0.2.0"
    assert c.main(["--write"]) == 0
    assert json.loads(snapshot.read_text(encoding="utf-8"))["version"] == "0.2.0"
    assert f"`{first}`" not in doc.read_text(encoding="utf-8")


def test_check_fails_when_the_snapshot_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    snapshot = tmp_path / "catalogue.json"
    stale = copy.deepcopy(LIVE)
    stale["tools"][0]["description"] = "something older"
    snapshot.write_text(c.dump(stale), encoding="utf-8")
    monkeypatch.setattr(c, "SNAPSHOT", snapshot)
    assert c.main([]) == 1
    assert "OUT OF SYNC" in capsys.readouterr().out

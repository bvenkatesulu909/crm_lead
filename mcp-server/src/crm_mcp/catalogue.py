"""The tool catalogue: what every MCP client sees, written down and checked (ADR 0015, D2).

``current_catalogue()`` reads the live tool list from the server. The committed copy
(``contract/catalogue.json``) and the table in ``docs/mcp-tools.md`` are generated from it with

    uv run python -m crm_mcp.catalogue --write

and a test fails when either drifts from the live server. ``--write`` also applies the version
rule, so a tool cannot be removed or changed silently:

* removing or renaming a tool or an input, adding a required input, narrowing a type or the
  allowed values, or making a tool less read-only is a **breaking** change;
* adding a tool, an optional input or an allowed value is a **compatible** change;
* a changed description alone is a **wording** change.

The contract version is the package version (``pyproject.toml``). Breaking changes need a new
major version (before 1.0: a new minor, e.g. 0.1 -> 0.2); compatible changes need at least a new
minor (before 1.0: a new patch); wording changes need no bump.
"""

import argparse
import asyncio
import json
import re
import sys
from importlib import metadata
from pathlib import Path
from typing import Any, Literal

Change = Literal["none", "wording", "compatible", "breaking"]
_ORDER: dict[str, int] = {"none": 0, "wording": 1, "compatible": 2, "breaking": 3}

ROOT = Path(__file__).resolve().parents[2]  # mcp-server/
SNAPSHOT = ROOT / "contract" / "catalogue.json"
DOC = ROOT.parent / "docs" / "mcp-tools.md"
BEGIN, END = "<!-- catalogue:begin (generated: do not edit) -->", "<!-- catalogue:end -->"

# Which CRM API endpoints each tool calls (all GET). The API applies tenant, role and record
# checks; a record the person may not see is answered as "not found".
ENDPOINTS: dict[str, tuple[str, ...]] = {
    "whoami": ("GET /me",),
    "search_leads": ("GET /leads",),
    "get_lead": ("GET /leads/{id}", "GET /leads/{id}/activities"),
    "search_accounts": ("GET /accounts",),
    "get_account": (
        "GET /accounts/{id}",
        "GET /contacts",
        "GET /opportunities",
    ),
    "list_my_tasks": ("GET /activities",),
    "list_opportunities": ("GET /opportunities",),
    "get_dashboard": ("GET /dashboard",),
}

TOOL_NAME = re.compile(r"^(get|search|list)_[a-z_]+$|^whoami$")
MAX_PAGE = 50


def contract_version() -> str:
    return metadata.version("crm-mcp")


def _strip_titles(value: Any) -> Any:
    """Generated ``title`` keys only repeat the field name; leaving them out keeps the
    catalogue about meaning, not about how the SDK words its schema."""
    if isinstance(value, dict):
        return {k: _strip_titles(v) for k, v in value.items() if k != "title"}
    if isinstance(value, list):
        return [_strip_titles(v) for v in value]
    return value


def current_catalogue() -> dict[str, Any]:
    from crm_mcp.server import build_server
    from crm_mcp.tools import CrmTools

    # Listing tools never calls the CRM, so the server can be built without a sign-in.
    server = build_server(CrmTools(None, None))  # type: ignore[arg-type]
    tools = asyncio.run(server.list_tools())
    entries = [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": _strip_titles(tool.input_schema),
            "annotations": tool.annotations.model_dump(by_alias=True, exclude_none=True)
            if tool.annotations
            else {},
            "endpoints": list(ENDPOINTS.get(tool.name, ())),
        }
        for tool in tools
    ]
    return {"version": contract_version(), "tools": sorted(entries, key=lambda t: t["name"])}


# --- comparing two catalogues ------------------------------------------------------------------


def _worse(old: Change, new: Change) -> Change:
    return new if _ORDER[new] > _ORDER[old] else old


def _compare_schema(old: dict[str, Any], new: dict[str, Any]) -> Change:
    result: Change = "none"
    old_props, new_props = old.get("properties", {}), new.get("properties", {})
    for name in old_props:
        if name not in new_props:
            result = _worse(result, "breaking")
    for name, prop in new_props.items():
        if name not in old_props:
            required = name in new.get("required", [])
            result = _worse(result, "breaking" if required else "compatible")
            continue
        result = _worse(result, _compare_property(old_props[name], prop))
    for name in set(new.get("required", [])) & set(old_props):
        if name not in old.get("required", []):
            result = _worse(result, "breaking")  # an optional input became required
    return result


def _enum_values(prop: Any) -> set[str] | None:
    """All allowed values anywhere inside a property schema, or None if it has no enum."""
    found: set[str] = set()
    seen = False

    def walk(node: Any) -> None:
        nonlocal seen
        if isinstance(node, dict):
            if "enum" in node:
                seen = True
                found.update(map(str, node["enum"]))
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(prop)
    return found if seen else None


def _types(prop: Any) -> set[str]:
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("type"), str):
                found.add(node["type"])
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(prop)
    return found


def _compare_property(old: dict[str, Any], new: dict[str, Any]) -> Change:
    result: Change = "none"
    old_values, new_values = _enum_values(old), _enum_values(new)
    if old_values is not None:
        if new_values is None or old_values - new_values:
            result = _worse(result, "breaking")
        elif new_values - old_values:
            result = _worse(result, "compatible")
    elif new_values is not None:
        result = _worse(result, "breaking")  # a free input now accepts fewer values
    old_types, new_types = _types(old), _types(new)
    if old_types - new_types:
        result = _worse(result, "breaking")
    elif new_types - old_types:
        result = _worse(result, "compatible")
    if old.get("default") != new.get("default"):
        result = _worse(result, "compatible")
    return result


def classify_change(old: dict[str, Any], new: dict[str, Any]) -> Change:
    """How the new catalogue differs from the old one, for clients written against the old."""
    old_tools = {t["name"]: t for t in old["tools"]}
    new_tools = {t["name"]: t for t in new["tools"]}
    result: Change = "none"
    for name, before in old_tools.items():
        after = new_tools.get(name)
        if after is None:
            return "breaking"
        result = _worse(result, _compare_schema(before["input_schema"], after["input_schema"]))
        if before["annotations"].get("readOnlyHint") and not after["annotations"].get(
            "readOnlyHint"
        ):
            result = _worse(result, "breaking")  # a tool that only read now may write
        if before["annotations"] != after["annotations"]:
            result = _worse(result, "compatible")
        if before["description"] != after["description"]:
            result = _worse(result, "wording")
    if set(new_tools) - set(old_tools):
        result = _worse(result, "compatible")
    return result


def _parts(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        raise ValueError(f"version '{version}' is not major.minor.patch")
    return int(match[1]), int(match[2]), int(match[3])


def bump_allows(change: Change, old_version: str, new_version: str) -> bool:
    """Does going from ``old_version`` to ``new_version`` cover ``change``?"""
    if change in ("none", "wording"):
        return _parts(new_version) >= _parts(old_version)
    old, new = _parts(old_version), _parts(new_version)
    if new < old:
        return False
    if old[0] == 0:  # before 1.0 the digits shift one place to the right
        breaking_ok = new[:2] > old[:2]
        compatible_ok = breaking_ok or new > old
    else:
        breaking_ok = new[0] > old[0]
        compatible_ok = breaking_ok or new[:2] > old[:2]
    return breaking_ok if change == "breaking" else compatible_ok


# --- the rules every tool must follow (ADR 0015, D2 and D6) ------------------------------------


def rule_violations(catalogue: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for tool in catalogue["tools"]:
        name = tool["name"]
        if not TOOL_NAME.match(name):
            problems.append(f"{name}: name must be get_*, search_*, list_* (or whoami)")
        if not (tool["description"] or "").strip():
            problems.append(f"{name}: needs a description")
        notes = tool["annotations"]
        if notes.get("readOnlyHint") is not True or notes.get("destructiveHint") is not False:
            problems.append(f"{name}: must be marked read-only and not destructive")
        if notes.get("idempotentHint") is not True or notes.get("openWorldHint") is not False:
            problems.append(f"{name}: must be marked idempotent and closed-world")
        if not tool["endpoints"]:
            problems.append(f"{name}: list the API endpoints it calls in ENDPOINTS")
        limit = tool["input_schema"].get("properties", {}).get("limit")
        if limit is not None and not 1 <= limit.get("default", MAX_PAGE + 1) <= MAX_PAGE:
            problems.append(f"{name}: the default page size must be 1-{MAX_PAGE}")
    unknown = set(ENDPOINTS) - {t["name"] for t in catalogue["tools"]}
    problems.extend(f"{name}: in ENDPOINTS but not a tool" for name in sorted(unknown))
    return problems


# --- the document ------------------------------------------------------------------------------


def _inputs(schema: dict[str, Any]) -> str:
    props, required = schema.get("properties", {}), set(schema.get("required", []))
    if not props:
        return "none"
    rows = []
    for name, prop in props.items():
        values = _enum_values(prop)
        kind = "/".join(sorted(_types(prop) - {"null"})) or "any"
        shown = f"`{name}` ({kind}{', required' if name in required else ''}"
        if "default" in prop and prop["default"] is not None:
            shown += f", default {json.dumps(prop['default'])}"
        shown += ")"
        if values:
            shown += " one of " + ", ".join(f"`{v}`" for v in sorted(values))
        rows.append(shown)
    return "<br>".join(rows)


def render_table(catalogue: dict[str, Any]) -> str:
    lines = [
        f"Contract version: **{catalogue['version']}** - {len(catalogue['tools'])} tools, all "
        "read-only.",
        "",
        "| Tool | What it does | Inputs | API calls |",
        "|---|---|---|---|",
    ]
    for tool in catalogue["tools"]:
        calls = "<br>".join(f"`{e}`" for e in tool["endpoints"])
        description = tool["description"].replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{tool['name']}` | {description} | {_inputs(tool['input_schema'])} | {calls} |"
        )
    return "\n".join(lines)


def render_doc(existing: str, catalogue: dict[str, Any]) -> str:
    """The document with the generated block replaced (everything else is hand-written)."""
    block = f"{BEGIN}\n{render_table(catalogue)}\n{END}"
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
    if not pattern.search(existing):
        raise ValueError("the document has no generated catalogue block")
    return pattern.sub(lambda _: block, existing)


def dump(catalogue: dict[str, Any]) -> str:
    return json.dumps(catalogue, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


# --- command line ------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check or regenerate the MCP tool catalogue.")
    parser.add_argument("--write", action="store_true", help="regenerate the snapshot and the doc")
    args = parser.parse_args(argv)
    new = current_catalogue()
    old = json.loads(SNAPSHOT.read_text(encoding="utf-8")) if SNAPSHOT.exists() else None
    problems = rule_violations(new)
    if problems:
        print("The catalogue breaks the rules:\n  " + "\n  ".join(problems))
        return 1
    change: Change = classify_change(old, new) if old else "compatible"
    print(f"Change since the committed catalogue: {change} (version {new['version']})")
    if not args.write:
        in_sync = old == new and DOC.read_text(encoding="utf-8") == render_doc(
            DOC.read_text(encoding="utf-8"), new
        )
        print("In sync." if in_sync else "OUT OF SYNC: run with --write.")
        return 0 if in_sync else 1
    if old and not bump_allows(change, old["version"], new["version"]):
        print(
            f"A {change} change needs a higher version than {old['version']} "
            "(see the rule in crm_mcp/catalogue.py); raise it in pyproject.toml, "
            "run `uv sync`, then try again."
        )
        return 1
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(dump(new), encoding="utf-8", newline="\n")
    DOC.write_text(render_doc(DOC.read_text(encoding="utf-8"), new), encoding="utf-8", newline="\n")
    print("Written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

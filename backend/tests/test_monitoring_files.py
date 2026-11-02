"""The Grafana dashboard, the Prometheus alerts and the runbook agree with the real metrics
(CRM-111, step LM3).

Nothing here talks to Prometheus or Grafana. It reads the files in ``infrastructure/monitoring`` and
checks what a person would only find out on a bad night: a panel or alert that asks for a metric
that does not exist, a label that no metric has, an alert whose runbook link goes nowhere, two
panels on top of each other, or an expression that would put a tenant or person into a shared
dashboard (ADR 0016: no tenant label on any metric).
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]  # no stubs; used only to read alerts.yml

from app.core.observability.metrics import REGISTRY

ROOT = Path(__file__).resolve().parents[2]
MONITORING = ROOT / "infrastructure" / "monitoring"
DASHBOARD = MONITORING / "grafana" / "dashboards" / "crm-lead-operations.json"
ALERTS = MONITORING / "alerts.yml"
RUNBOOK = ROOT / "docs" / "r6-operations-runbook.md"

METRIC = re.compile(r"\bcrm_[a-z0-9_]+")
LABELS = re.compile(r"(?:by|without)\s*\(([^)]*)\)|\{([^}]*)\}")
PEOPLE_AND_TENANTS = ("tenant", "user", "person", "question", "answer", "prompt", "email")


def known_series() -> dict[str, set[str]]:
    """Every series name Prometheus will see (with _total, _bucket ...) -> the labels it has."""
    names: dict[str, set[str]] = {}
    for series, collector in REGISTRY._names_to_collectors.items():
        labels = set(getattr(collector, "_labelnames", ()))
        names[series] = labels | ({"le"} if series.endswith("_bucket") else set())
    return names


SERIES = known_series()


def dashboard() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    return data


def alert_rules() -> list[dict[str, Any]]:
    groups = yaml.safe_load(ALERTS.read_text(encoding="utf-8"))["groups"]
    return [rule for group in groups for rule in group["rules"]]


def expressions() -> list[tuple[str, str]]:
    found = [
        (f"panel '{p['title']}'", t["expr"])
        for p in dashboard()["panels"]
        for t in p.get("targets", [])
    ]
    found += [(f"alert {r['alert']}", r["expr"]) for r in alert_rules()]
    return found


def label_names(expr: str) -> set[str]:
    names: set[str] = set()
    for grouping, matchers in LABELS.findall(expr):
        for part in (grouping or "").split(","):
            if part.strip():
                names.add(part.strip())
        for match in re.finditer(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:=~|!~|!=|=)", matchers or ""):
            names.add(match.group(1))
    return names


def runbook_anchors() -> set[str]:
    return set(re.findall(r"\{#([a-z0-9-]+)\}", RUNBOOK.read_text(encoding="utf-8")))


# --- the files are well formed ----------------------------------------------------------------


def test_the_dashboard_is_valid_and_its_panels_do_not_overlap() -> None:
    panels = dashboard()["panels"]
    ids = [p["id"] for p in panels]
    assert len(ids) == len(set(ids)), "two panels share an id"
    boxes = [(p["title"], p["gridPos"]) for p in panels]
    for i, (name_a, a) in enumerate(boxes):
        assert 0 <= a["x"] and a["x"] + a["w"] <= 24, f"{name_a} leaves the 24-column grid"
        for name_b, b in boxes[i + 1 :]:
            apart = (
                a["x"] + a["w"] <= b["x"]
                or b["x"] + b["w"] <= a["x"]
                or a["y"] + a["h"] <= b["y"]
                or b["y"] + b["h"] <= a["y"]
            )
            assert apart, f"'{name_a}' and '{name_b}' overlap"


def test_the_alert_file_is_valid_prometheus_yaml_with_the_usual_parts() -> None:
    rules = alert_rules()
    assert rules
    names = [r["alert"] for r in rules]
    assert len(names) == len(set(names)), "two alerts share a name"
    for rule in rules:
        assert rule["expr"].strip() and rule["labels"]["severity"] in {"warning", "critical"}
        assert rule["annotations"]["summary"].strip()


# --- they ask for things that exist ------------------------------------------------------------


@pytest.mark.parametrize(("where", "expr"), expressions(), ids=lambda v: str(v)[:60])
def test_every_metric_in_an_expression_exists(where: str, expr: str) -> None:
    for name in METRIC.findall(expr):
        assert name in SERIES, f"{where} uses '{name}', which no metric produces"


@pytest.mark.parametrize(("where", "expr"), expressions(), ids=lambda v: str(v)[:60])
def test_every_label_in_an_expression_belongs_to_a_metric_it_uses(where: str, expr: str) -> None:
    allowed = {"le"}
    for name in METRIC.findall(expr):
        allowed |= SERIES.get(name, set())
    unknown = label_names(expr) - allowed
    assert not unknown, f"{where} groups or filters by {sorted(unknown)}, which its metrics lack"


@pytest.mark.parametrize(("where", "expr"), expressions(), ids=lambda v: str(v)[:60])
def test_no_expression_puts_a_tenant_or_a_person_on_screen(where: str, expr: str) -> None:
    for label in label_names(expr):
        assert not any(word in label.lower() for word in PEOPLE_AND_TENANTS), (where, label)


def test_no_metric_has_a_label_that_could_identify_a_tenant_or_a_person() -> None:
    for series, labels in SERIES.items():
        if series.startswith("crm_ai_") or series.startswith("crm_qualifier_"):
            for label in labels:
                assert not any(word in label.lower() for word in PEOPLE_AND_TENANTS), (
                    series,
                    label,
                )


# --- the runbook goes with the alerts ------------------------------------------------------------


def test_every_alert_links_to_a_runbook_section_that_exists() -> None:
    anchors = runbook_anchors()
    for rule in alert_rules():
        link = rule["annotations"].get("runbook", "")
        assert link.startswith("docs/r6-operations-runbook.md#"), rule["alert"]
        assert link.split("#", 1)[1] in anchors, f"{rule['alert']}: no section for {link}"


def test_every_alert_is_in_the_runbook_table() -> None:
    table = RUNBOOK.read_text(encoding="utf-8")
    for rule in alert_rules():
        assert f"| {rule['alert']} |" in table, f"{rule['alert']} is not in the runbook table"


# --- CRM-111: the AI view is per agent ------------------------------------------------------------

AGENT_PANELS = {
    "AI cost by agent (USD per hour)": ("crm_ai_estimated_cost_usd_total", "agent"),
    "AI tokens by agent": ("crm_ai_tokens_total", "agent"),
    "AI p95 latency by agent": ("crm_ai_request_duration_seconds_bucket", "agent"),
    "AI failed calls by agent": ("crm_ai_requests_total", "agent"),
    "AI calls refused by agent": ("crm_ai_refusals_total", "agent"),
}


@pytest.mark.parametrize("title", AGENT_PANELS)
def test_the_dashboard_has_a_panel_per_agent_view(title: str) -> None:
    panels = {p["title"]: p for p in dashboard()["panels"]}
    assert title in panels, f"missing panel: {title}"
    metric, label = AGENT_PANELS[title]
    exprs = " ".join(t["expr"] for t in panels[title]["targets"])
    assert metric in exprs and re.search(rf"by\s*\([^)]*\b{label}\b", exprs), title


def test_the_old_cost_panel_adds_the_agents_up() -> None:
    panels = {p["title"]: p for p in dashboard()["panels"]}
    exprs = [t["expr"] for t in panels["AI tokens / cost"]["targets"]]
    cost = next(e for e in exprs if "estimated_cost" in e)
    assert cost.startswith("sum(") or cost.startswith("sum by"), cost


def test_the_cost_alert_adds_the_agents_up() -> None:
    rule = next(r for r in alert_rules() if r["alert"] == "CrmAiCostBudget")
    assert rule["expr"].startswith("sum("), rule["expr"]


def test_one_agent_failing_has_its_own_alert_that_ignores_quiet_agents() -> None:
    rule = next(r for r in alert_rules() if r["alert"] == "CrmAiAgentFailing")
    expr = rule["expr"]
    assert "by (agent)" in expr and "crm_ai_requests_total" in expr
    # A guard against alerting on two failed calls out of three: needs real traffic first.
    assert "increase(crm_ai_requests_total" in expr and ">= 5" in expr
    assert rule["labels"]["severity"] == "warning" and rule["for"] in {"15m", "20m", "30m"}
    assert "agent" in rule["annotations"]["summary"].lower()


def test_the_runbook_tells_how_to_find_the_agent_and_no_longer_says_deepseek_is_missing() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "by agent" in text.lower() or "per agent" in text.lower()
    assert "DeepSeek is **not implemented**" not in text

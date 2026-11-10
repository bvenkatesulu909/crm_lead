"""The dependency audit's judge (BP-20, step SG2): what fails the build and what does not.

Pure: reports and exception files are written in the test, no network and no pip-audit run.
"""

import json
from datetime import date
from pathlib import Path

from scripts.check_audit import Verdict, judge, main, read_exceptions, read_report

REPO = Path(__file__).resolve().parents[2]
TODAY = date(2026, 11, 10)


def report(*vulns: tuple[str, str, str, list[str]]) -> str:
    """(package, version, advisory id, aliases) -> pip-audit JSON."""
    deps: dict[str, dict[str, object]] = {}
    for package, version, advisory, aliases in vulns:
        entry = deps.setdefault(package, {"name": package, "version": version, "vulns": []})
        entry["vulns"].append(  # type: ignore[attr-defined]
            {"id": advisory, "aliases": aliases, "fix_versions": ["9.9.9"]}
        )
    deps.setdefault("clean", {"name": "clean", "version": "1.0", "vulns": []})
    return json.dumps({"dependencies": list(deps.values()), "fixes": []})


def exceptions(*entries: str) -> str:
    return "\n".join(entries)


def entry(
    advisory: str = "GHSA-aaaa",
    package: str = "pillow",
    reason: str = "No fixed release yet; the affected decoder is never used.",
    added: str = "2026-11-01",
    expires: str = "2026-11-30",
) -> str:
    return (
        f'[[exception]]\nid = "{advisory}"\npackage = "{package}"\nreason = "{reason}"\n'
        f"added = {added}\nexpires = {expires}\n"
    )


def verdict(report_text: str, exceptions_text: str = "") -> Verdict:
    entries, problems = read_exceptions(exceptions_text)
    assert problems == [], problems
    return judge(read_report(report_text), entries, TODAY)


def test_a_clean_report_passes() -> None:
    assert verdict(report()).ok


def test_an_advisory_without_an_exception_fails_and_names_the_fix() -> None:
    result = verdict(report(("pillow", "12.3.0", "GHSA-aaaa", [])))
    assert not result.ok
    assert "pillow 12.3.0: GHSA-aaaa, fixed in 9.9.9" in result.failures[0]


def test_a_current_exception_lets_it_pass_but_says_so() -> None:
    result = verdict(report(("pillow", "12.3.0", "GHSA-aaaa", [])), entry())
    assert result.ok
    assert any("allowed until 2026-11-30" in n for n in result.notes)


def test_an_exception_may_name_an_alias() -> None:
    result = verdict(
        report(("pillow", "12.3.0", "PYSEC-1", ["GHSA-aaaa", "CVE-2026-1"])),
        entry(advisory="CVE-2026-1"),
    )
    assert result.ok


def test_an_exception_for_another_package_does_not_count() -> None:
    result = verdict(report(("pillow", "12.3.0", "GHSA-aaaa", [])), entry(package="reportlab"))
    assert not result.ok


def test_an_expired_exception_fails_even_when_nothing_matches() -> None:
    result = verdict(report(), entry(added="2026-10-01", expires="2026-10-31"))
    assert not result.ok
    assert "expired on 2026-10-31" in result.failures[0]


def test_an_unused_exception_is_only_a_note() -> None:
    result = verdict(report(), entry())
    assert result.ok
    assert any("matches nothing" in n for n in result.notes)


def test_badly_written_exceptions_are_refused() -> None:
    for bad, message in [
        (entry(reason="ok"), "give a real reason"),
        (entry(added="2026-11-01", expires="2026-12-31"), "at most 30 days"),
        (entry(added="2026-11-10", expires="2026-11-01"), "expires must be after added"),
        ('[[exception]]\nid = "GHSA-aaaa"\n', "needs id, package, reason"),
    ]:
        _, problems = read_exceptions(bad)
        assert any(message in p for p in problems), (bad, problems)


def test_the_command_exit_codes(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(report(("pillow", "12.3.0", "GHSA-aaaa", [])), encoding="utf-8")
    good = tmp_path / "good.json"
    good.write_text(report(), encoding="utf-8")
    none = tmp_path / "none.toml"
    none.write_text("", encoding="utf-8")
    allowed = tmp_path / "allowed.toml"
    allowed.write_text(entry(), encoding="utf-8")
    assert main([str(good), "--exceptions", str(none), "--today", "2026-11-10"]) == 0
    assert main([str(bad), "--exceptions", str(none), "--today", "2026-11-10"]) == 1
    assert main([str(bad), "--exceptions", str(allowed), "--today", "2026-11-10"]) == 0
    assert main([str(bad), "--exceptions", str(allowed), "--today", "2026-12-01"]) == 1


def test_the_repository_exceptions_file_is_valid_and_current() -> None:
    text = (REPO / "security" / "audit-exceptions.toml").read_text(encoding="utf-8")
    entries, problems = read_exceptions(text)
    assert problems == []
    assert all(e.expires >= date.today() for e in entries), "an exception has expired"

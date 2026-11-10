"""Judge a ``pip-audit`` report against the dated exceptions (BP-20, docs/ci-security-gate.md).

``pip-audit -f json`` lists every package with its known advisories. This script fails when:

* a package has an advisory that is not in ``security/audit-exceptions.toml``;
* an exception has expired (an exception is a reminder with a deadline, not a permanent "ignore");
* an exception has no reason, no expiry, or an expiry more than 30 days after it was added.

An exception that matches nothing any more is only reported (the fix landed; delete the entry).

Run (in ``backend``):
``python -m scripts.check_audit report.json --exceptions ../security/audit-exceptions.toml``
(more reports may follow the first). Exit code 1 when the build must fail.
"""

from __future__ import annotations

import argparse
import json
import tomllib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

MAX_DAYS = 30


@dataclass(frozen=True)
class Advisory:
    package: str
    version: str
    advisory_id: str
    aliases: frozenset[str]
    fixed_in: tuple[str, ...]


@dataclass(frozen=True)
class Exception_:
    advisory_id: str
    package: str
    reason: str
    added: date
    expires: date


def read_report(text: str) -> list[Advisory]:
    data = json.loads(text)
    packages = data["dependencies"] if isinstance(data, dict) else data
    found: list[Advisory] = []
    for package in packages:
        for vuln in package.get("vulns", []):
            found.append(
                Advisory(
                    package=str(package["name"]).lower(),
                    version=str(package.get("version", "")),
                    advisory_id=str(vuln["id"]),
                    aliases=frozenset(str(a) for a in vuln.get("aliases", [])),
                    fixed_in=tuple(str(v) for v in vuln.get("fix_versions", [])),
                )
            )
    return found


def read_exceptions(text: str) -> tuple[list[Exception_], list[str]]:
    """The exceptions, and what is wrong with the file itself (each problem fails the build)."""
    problems: list[str] = []
    entries: list[Exception_] = []
    for number, raw in enumerate(tomllib.loads(text).get("exception", []), start=1):
        where = f"exception #{number}"
        try:
            advisory_id = str(raw["id"]).strip()
            package = str(raw["package"]).strip().lower()
            reason = str(raw.get("reason", "")).strip()
            added = _as_date(raw["added"])
            expires = _as_date(raw["expires"])
        except (KeyError, TypeError, ValueError) as exc:
            problems.append(f"{where}: needs id, package, reason, added and expires ({exc})")
            continue
        if not advisory_id or not package:
            problems.append(f"{where}: id and package must not be empty")
            continue
        if len(reason) < 10:
            problems.append(f"{where} ({advisory_id}): give a real reason")
        if expires <= added:
            problems.append(f"{where} ({advisory_id}): expires must be after added")
        if (expires - added).days > MAX_DAYS:
            problems.append(
                f"{where} ({advisory_id}): at most {MAX_DAYS} days between added and expires"
            )
        entries.append(Exception_(advisory_id, package, reason, added, expires))
    return entries, problems


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


@dataclass
class Verdict:
    failures: list[str]
    notes: list[str]

    @property
    def ok(self) -> bool:
        return not self.failures


def judge(advisories: list[Advisory], exceptions: list[Exception_], today: date) -> Verdict:
    failures: list[str] = []
    notes: list[str] = []
    used: set[tuple[str, str]] = set()
    for exc in exceptions:
        if exc.expires < today:
            failures.append(
                f"exception for {exc.advisory_id} ({exc.package}) expired on {exc.expires}: "
                "fix the package or renew the exception with a new reason"
            )
    for adv in advisories:
        names = {adv.advisory_id, *adv.aliases}
        match = next(
            (e for e in exceptions if e.package == adv.package and e.advisory_id in names),
            None,
        )
        if match is None:
            fix = f", fixed in {', '.join(adv.fixed_in)}" if adv.fixed_in else ", no fix yet"
            failures.append(f"{adv.package} {adv.version}: {adv.advisory_id}{fix}")
        else:
            used.add((match.package, match.advisory_id))
            if match.expires >= today:
                notes.append(
                    f"{adv.package} {adv.version}: {adv.advisory_id} allowed until "
                    f"{match.expires} - {match.reason}"
                )
    for exc in exceptions:
        if (exc.package, exc.advisory_id) not in used and exc.expires >= today:
            notes.append(
                f"exception for {exc.advisory_id} ({exc.package}) matches nothing: remove it"
            )
    return Verdict(failures, notes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("reports", nargs="+", type=Path, help="pip-audit JSON reports")
    parser.add_argument("--exceptions", type=Path, required=True)
    parser.add_argument("--today", type=date.fromisoformat, default=None, help="for tests")
    args = parser.parse_args(argv)
    advisories = [a for r in args.reports for a in read_report(r.read_text(encoding="utf-8"))]
    exceptions, problems = read_exceptions(args.exceptions.read_text(encoding="utf-8"))
    today = args.today or datetime.now(UTC).date()
    verdict = judge(advisories, exceptions, today)
    for line in problems + verdict.failures:
        print(f"FAIL  {line}")  # noqa: T201 - a command-line report
    for line in verdict.notes:
        print(f"note  {line}")  # noqa: T201
    if problems or verdict.failures:
        print(  # noqa: T201
            f"{len(problems) + len(verdict.failures)} problem(s). Update the package, or add "
            "a dated exception with a reason to security/audit-exceptions.toml."
        )
        return 1
    if advisories:
        print(f"{len(advisories)} known advisory(ies), each with a current exception.")  # noqa: T201
    else:
        print("No known advisories.")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

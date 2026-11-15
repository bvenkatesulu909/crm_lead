"""Money is never a float (BP-20, docs/ci-security-gate.md).

A float cannot hold 0.1 exactly, so sums of prices drift by fractions of a cent; the CRM keeps
money in ``Decimal`` / ``NUMERIC``. This checker reads the Python source (it imports nothing) and
reports:

* a ``float`` annotation on a name that looks like money - a variable, attribute, setting or
  parameter called ``price``, ``amount``, ``total_inr``, ``cost``, … (also ``float | None``);
* ``float(<something that looks like money>)``;
* any ``Float`` / ``Double`` / ``REAL`` database column type (money columns are ``Numeric``; the
  CRM has no other use for floating-point columns either).

A real exception carries a marker on the same line with a reason, for example
``.inc(float(cost))  # money-float-ok: Prometheus counters only take float``. A marker without a
reason does not count.

Run: ``python -m scripts.check_money_types`` (in ``backend``); exit code 1 when something is found.
The backend test suite runs it on ``app`` and ``alembic`` (``tests/test_money_types.py``).
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Words that mean money in this code base. Matched against identifiers split on "_", so
# "total_seconds" is not money but "total_inr" and "price_per_million" are.
MONEY_WORDS = frozenset(
    {
        "amount",
        "amounts",
        "price",
        "prices",
        "cost",
        "costs",
        "fee",
        "fees",
        "tax",
        "taxes",
        "subtotal",
        "revenue",
        "budget",
        "balance",
        "payment",
        "payments",
        "money",
        "inr",
        "eur",
        "usd",
        "rupees",
        "paise",
        "cents",
    }
)
# "total" alone is often a count; it is money only next to a currency or another money word.
_CURRENCY = frozenset({"inr", "eur", "usd", "rupees", "paise", "cents"})
FLOAT_COLUMN_TYPES = frozenset({"Float", "Double", "DOUBLE", "DOUBLE_PRECISION", "REAL"})
MARKER = re.compile(r"#\s*money-float-ok:\s*\S")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    what: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.what}"


def _words(name: str) -> list[str]:
    # camelCase and snake_case both split into lower-case words
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return [w for w in spaced.lower().split("_") if w]


def looks_like_money(name: str) -> bool:
    words = _words(name)
    if any(w in MONEY_WORDS for w in words):
        return True
    return "total" in words and any(w in _CURRENCY for w in words)


def _names_in(node: ast.AST) -> list[str]:
    names: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.append(child.id)
        elif isinstance(child, ast.Attribute):
            names.append(child.attr)
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            names.append(child.value)
    return names


def _is_float_annotation(node: ast.AST | None) -> bool:
    if node is None:
        return False
    if isinstance(node, ast.Name):
        return node.id == "float"
    if isinstance(node, ast.Constant) and isinstance(node.value, str):  # "float" as a string
        return node.value.replace(" ", "") in {"float", "float|None", "Optional[float]"}
    if isinstance(node, ast.BinOp):  # float | None
        return _is_float_annotation(node.left) or _is_float_annotation(node.right)
    if isinstance(node, ast.Subscript):  # Optional[float], Mapped[float], list[float]
        return _is_float_annotation(node.slice)
    if isinstance(node, ast.Tuple):
        return any(_is_float_annotation(e) for e in node.elts)
    return False


def _callee(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def check_source(source: str, path: str = "<source>") -> list[Finding]:
    tree = ast.parse(source, filename=path)
    lines = source.splitlines()
    found: list[Finding] = []

    def report(node: ast.AST, what: str) -> None:
        line = getattr(node, "lineno", 0)
        text = lines[line - 1] if 0 < line <= len(lines) else ""
        if not MARKER.search(text):
            found.append(Finding(path, line, what))

    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            target = node.target
            name = (
                target.id
                if isinstance(target, ast.Name)
                else target.attr
                if isinstance(target, ast.Attribute)
                else ""
            )
            if name and looks_like_money(name) and _is_float_annotation(node.annotation):
                report(node, f"'{name}' looks like money but is a float - use Decimal")
        elif isinstance(node, ast.arg):
            if looks_like_money(node.arg) and _is_float_annotation(node.annotation):
                report(node, f"parameter '{node.arg}' looks like money but is a float")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if looks_like_money(node.name) and _is_float_annotation(node.returns):
                report(node, f"'{node.name}' looks like money but returns a float")
        elif isinstance(node, ast.Call):
            callee = _callee(node)
            if callee == "float" and node.args:
                money = [n for n in _names_in(node.args[0]) if looks_like_money(n)]
                if money:
                    report(node, f"float({money[0]}): money turned into a float")
        elif isinstance(node, ast.Attribute) and node.attr in FLOAT_COLUMN_TYPES:
            # sa.Float or sa.Float(): the type itself, called or not
            report(node, f"{node.attr} column type: money and amounts are Numeric")
        elif (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in FLOAT_COLUMN_TYPES
        ):
            # Float / Double imported and passed bare, e.g. mapped_column(Double)
            report(node, f"{node.id} column type: money and amounts are Numeric")
    # one finding per line and kind is enough
    unique = {(f.line, f.what): f for f in found}
    return sorted(unique.values(), key=lambda f: (f.line, f.what))


def check_paths(roots: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for root in roots:
        files = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for file in files:
            findings.extend(check_source(file.read_text(encoding="utf-8"), file.as_posix()))
    return findings


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    roots = [Path(a) for a in args] or [Path("app"), Path("alembic")]
    findings = check_paths(roots)
    for finding in findings:
        print(finding)  # noqa: T201 - a command-line report
    if findings:
        print(  # noqa: T201
            f"{len(findings)} place(s) keep money as a float. Use Decimal, or add "
            "'# money-float-ok: <reason>' on the line when a float is truly required."
        )
        return 1
    print("No money kept as a float.")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

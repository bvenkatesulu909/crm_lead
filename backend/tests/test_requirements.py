"""Every library the app imports must come with requirements.txt (the runtime install).

Why: the developer's virtual environment also contains test tools and things installed by hand,
so a missing line in requirements.txt only shows up on a CLEAN install - e.g. in the container
image used for deployment (ADR 0007). This test finds that mistake early.
"""

import ast
import importlib.metadata as metadata
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _normal(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _direct_requirements() -> set[str]:
    names = set()
    for line in (BACKEND / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line:
            names.add(_normal(re.split(r"[\[=<>!~ ;]", line)[0]))
    return names


def _closure(direct: set[str]) -> set[str]:
    """The requirements and everything they pull in (needed by libraries imported indirectly)."""
    seen: set[str] = set()
    todo = list(direct)
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        try:
            requires = metadata.requires(name) or []
        except metadata.PackageNotFoundError:
            continue
        for requirement in requires:
            if "extra ==" in requirement:
                continue  # optional extras are not installed unless asked for
            todo.append(_normal(re.split(r"[\[=<>!~ ;(]", requirement.strip())[0]))
    return seen


def _imported_modules() -> set[str]:
    modules: set[str] = set()
    for folder in ("app", "scripts"):
        for path in (BACKEND / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    modules |= {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    modules.add(node.module.split(".")[0])
    # agent_evals is the development-only evaluation harness (BP-10): not in the Docker image,
    # only scripts/eval_agents.py imports it.
    return modules - set(sys.stdlib_module_names) - {"app", "scripts", "agent_evals"}


def test_every_imported_library_is_in_the_runtime_requirements() -> None:
    installed_by = metadata.packages_distributions()
    covered = _closure(_direct_requirements())
    missing = {}
    for module in sorted(_imported_modules()):
        distributions = {_normal(d) for d in installed_by.get(module, [])}
        if not distributions & covered:
            missing[module] = sorted(distributions) or ["(not installed)"]
    assert not missing, (
        f"Imported but not covered by requirements.txt: {missing}. "
        "Add the library to requirements.txt (a clean install would crash)."
    )

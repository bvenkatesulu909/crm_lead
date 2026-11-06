"""The one-server guides stay true to the files (ADR 0021, step OH4).

A guide that links to a file that moved, or never mentions a script that exists, sends a beginner
to a dead end on the one night the server is down. These tests read the Markdown and check it
against the folder.
"""

import re
from pathlib import Path

import pytest

from tests.test_one_host_files import FOLDER, ROOT

GUIDES = [
    ROOT / "docs" / "deployment.md",
    ROOT / "docs" / "one-host-hardening.md",
    ROOT / "docs" / "adr" / "0021-one-host-deployment.md",
    FOLDER / "README.md",
]
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


def links(guide: Path) -> list[str]:
    found = LINK.findall(guide.read_text(encoding="utf-8"))
    return [target for target in found if not re.match(r"[a-z]+:", target)]  # not http:, mailto:


@pytest.mark.parametrize("guide", GUIDES, ids=lambda p: p.name)
def test_every_relative_link_points_at_a_file_that_exists(guide: Path) -> None:
    for target in links(guide):
        assert (guide.parent / target).resolve().exists(), f"{guide.name} -> {target}"


def test_the_readme_names_every_script_and_file_of_the_folder() -> None:
    readme = (FOLDER / "README.md").read_text(encoding="utf-8")
    table = readme[
        readme.index("## Files") :
    ]  # the table lists them all, not just a passing mention
    for path in [*FOLDER.glob("bin/*"), *FOLDER.glob("backup/*"), *FOLDER.glob("rehearsal/*")]:
        if path.is_file():
            relative = path.relative_to(FOLDER).as_posix()
            assert f"`{relative}`" in table, f"the Files table of README.md lacks {relative}"
    for name in ("docker-compose.yml", "Caddyfile", ".env.example", "tls.caddy"):
        assert f"`{name}`" in table, name


def test_the_deployment_guide_has_the_one_server_path_and_its_checklist() -> None:
    text = (ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")
    assert "## Two ways to host it" in text and "D2 on one server" in text
    for item in (
        "server-check.sh",
        "restore-test.sh",
        "RESTORE TEST PASSED",
        "password manager",
        "ADMIN_ALLOWED_IPS=127.0.0.1",
    ):
        assert item in text, item
    # Since 2026-11-06 the path runs on a real (staging) server. The guide must say when, and the
    # ticked lines must say when they were checked, so a tick never stands without evidence.
    assert "First real server: 2026-11-06" in text, "the guide must say when it first ran for real"
    assert 'not "go live"' in text, "staging must not be presented as live"
    restore = re.search(r"- \[x\] .*restore-test\.sh.*RESTORE TEST PASSED.*\n\s+\(2026-", text)
    assert restore, "the restore-test line is ticked only with the date it passed"
    server_check = re.search(r"- \[x\] .*server-check\.sh(.*\n)?.*0 FAIL", text)
    assert server_check, "the server check is ticked only with its result"
    # Lines nobody has checked yet stay open.
    assert re.search(r"- \[ \] A copy of the server's `\.env` is in your password manager", text)


def test_the_guides_say_honestly_where_the_one_server_path_stands() -> None:
    # Staging on a real server since 2026-11-06; neither guide may call it live.
    for guide in (FOLDER / "README.md", ROOT / "docs" / "one-host-hardening.md"):
        text = guide.read_text(encoding="utf-8").lower()
        assert "2026-11-06" in text and "staging" in text, guide.name
        assert "is live" not in text and "went live" not in text, guide.name


def test_the_adr_index_lists_the_decision_as_accepted() -> None:
    index = (ROOT / "docs" / "adr" / "README.md").read_text(encoding="utf-8")
    assert re.search(r"0021-one-host-deployment\.md\).*\| Accepted \|", index)

# ruff: noqa: S603, S607 - runs docker and bash by name on purpose, on files of this repository
"""The local rehearsal and the server hardening aids of the one-server deployment (ADR 0021, OH3).

The rehearsal starts the REAL stack on a PC with a throwaway certificate authority, so the proxy,
the HTTPS names, the sign-in service and the API can be tried together without a server. These tests
read the files and check that the rehearsal can never leak into production: the production files
must stay free of anything rehearsal-only, and the rehearsal must be loudly marked.
"""

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]  # no stubs; used only to read the compose files

from tests.test_one_host_backup import code, working_bash
from tests.test_one_host_files import (
    CADDYFILE,
    COMPOSE,
    FOLDER,
    ROOT,
    docker_ready,
    filled,
    fresh,
)

REHEARSAL = FOLDER / "rehearsal"
OVERRIDE = REHEARSAL / "docker-compose.rehearsal.yml"
TLS_PRODUCTION = FOLDER / "tls.caddy"
TLS_REHEARSAL = REHEARSAL / "tls.caddy"
SMOKE = REHEARSAL / "smoke.sh"
SERVER_CHECK = FOLDER / "bin" / "server-check.sh"
HARDENING = ROOT / "docs" / "one-host-hardening.md"


class _ComposeLoader(yaml.SafeLoader):  # type: ignore[misc]  # PyYAML has no type stubs
    """Reads the Compose-only tags (`!override`, `!reset`) as the plain value they wrap."""


def _wrapped(loader: yaml.SafeLoader, node: yaml.Node) -> object:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    return loader.construct_scalar(node)


_ComposeLoader.add_constructor("!override", _wrapped)
_ComposeLoader.add_constructor("!reset", _wrapped)


def override() -> dict[str, Any]:
    data: dict[str, Any] = yaml.load(OVERRIDE.read_text(encoding="utf-8"), _ComposeLoader)  # noqa: S506
    return data


def directives(path: Path) -> list[str]:
    """What a Caddy snippet file really says: its lines without comments and blanks."""
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


# --- production stays free of anything rehearsal-only -------------------------------------------


def test_the_production_certificates_are_the_default_ones() -> None:
    # No "tls internal", no custom authority, no local certificates: Caddy's own default is
    # Let's Encrypt for the names in the Caddyfile.
    assert directives(TLS_PRODUCTION) == []


def test_both_sites_take_their_certificate_settings_from_that_one_file() -> None:
    text = CADDYFILE.read_text(encoding="utf-8")
    assert text.count("import /etc/caddy/tls.caddy") == 2
    assert "tls internal" not in text and "local_certs" not in text and "acme_ca" not in text


def test_the_production_compose_file_mounts_the_production_tls_file() -> None:
    caddy = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["caddy"]
    assert "./tls.caddy:/etc/caddy/tls.caddy:ro" in caddy["volumes"]


def test_nothing_rehearsal_only_is_in_the_production_compose_file() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    for word in ("rehearsal", "8443", "8080", "SSL_CERT_FILE", "tls internal"):
        assert word not in text, word
    assert not re.search(r"127\.0\.0\.1:\d+:\d+", text), "a port published on this PC only"


# --- the rehearsal override ---------------------------------------------------------------------


def test_the_override_is_marked_as_never_for_a_real_server() -> None:
    for path in (OVERRIDE, TLS_REHEARSAL, SMOKE):
        head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:6])
        assert "NEVER" in head and "real server" in head, path.name


def test_the_rehearsal_certificates_come_from_a_throwaway_authority() -> None:
    assert directives(TLS_REHEARSAL) == ["tls internal"]


def test_the_override_replaces_the_tls_file_and_publishes_only_on_this_pc_on_other_ports() -> None:
    services = override()["services"]
    caddy = services["caddy"]
    assert "./rehearsal/tls.caddy:/etc/caddy/tls.caddy:ro" in caddy["volumes"]
    ports = caddy["ports"]
    assert set(ports) == {"127.0.0.1:8080:80", "127.0.0.1:8443:443"}, "never 80/443, never 0.0.0.0"


def test_the_override_touches_only_the_proxy_and_the_trust_of_the_api_and_worker() -> None:
    services = override()["services"]
    assert set(services) == {"caddy", "api", "worker", "rehearsal-ca"}
    for name in ("api", "worker"):
        service = services[name]
        assert set(service) == {"environment", "volumes", "depends_on"}, name
        assert set(service["environment"]) == {"SSL_CERT_FILE"}, name
        assert service["volumes"] == ["rehearsal_ca:/rehearsal-ca:ro"], name
        assert (
            service["depends_on"]["rehearsal-ca"]["condition"] == "service_completed_successfully"
        )
        trust = service["environment"]["SSL_CERT_FILE"]
        assert "/rehearsal-ca/root.crt" in trust, name


def test_the_api_and_worker_keep_running_as_the_unprivileged_user() -> None:
    # Found by really running it: the API (user crm) could not read the proxy's private data volume
    # and crashed in a loop. The cure is NOT to run it as root (that would hide real permission
    # problems); a helper copies only the PUBLIC root certificate to a readable volume instead.
    text = OVERRIDE.read_text(encoding="utf-8")
    assert "user:" not in text and "root.crt" in text
    helper = override()["services"]["rehearsal-ca"]
    assert helper["restart"] == "no" and not helper.get("ports")
    assert "caddy_data:/data:ro" in helper["volumes"], "the helper only reads the proxy's data"
    command = " ".join(helper["command"])
    assert "chmod 0644" in command and "root.crt" in command
    assert "key" not in command.lower().replace("keycloak", ""), "never the private key"


def test_the_proxy_may_start_before_the_api_in_the_rehearsal_only() -> None:
    # The certificate authority is created by the proxy, the API needs its public certificate to
    # start, so in the rehearsal the order is reversed. Production keeps api and keycloak first.
    caddy = override()["services"]["caddy"]
    assert caddy["depends_on"] == ["keycloak"]
    production = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["caddy"]
    assert set(production["depends_on"]) == {"api", "keycloak"}


def test_the_override_does_not_weaken_a_single_setting_of_the_production_stack() -> None:
    text = OVERRIDE.read_text(encoding="utf-8")
    for forbidden in (
        "CRM_ENVIRONMENT",
        "privileged",
        "network_mode",
        "cap_add",
        "CRM_DOCS_ENABLED",
        "ADMIN_ALLOWED_IPS",
        "BYPASSRLS",
    ):
        assert not re.search(rf"\b{forbidden}\b", text), forbidden


@pytest.mark.skipif(not docker_ready(), reason="Docker is not available")
def test_docker_compose_accepts_the_base_file_with_the_override(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(filled(fresh()), encoding="utf-8")
    result = subprocess.run(
        ["docker", "compose", "--env-file", str(env), "-f", str(COMPOSE), "-f", str(OVERRIDE)]
        + ["config", "--format", "json"],
        capture_output=True,
        text=True,
        cwd=FOLDER,
    )
    assert result.returncode == 0, result.stderr
    merged = yaml.safe_load(result.stdout)
    ports = merged["services"]["caddy"]["ports"]
    assert {(p["host_ip"], p["published"]) for p in ports} == {
        ("127.0.0.1", "8080"),
        ("127.0.0.1", "8443"),
    }
    volumes = merged["services"]["caddy"]["volumes"]
    tls = next(v for v in volumes if v["target"] == "/etc/caddy/tls.caddy")
    assert tls["source"].replace("\\", "/").endswith("rehearsal/tls.caddy"), "swapped, not added"
    # The ports of every other service are still none at all.
    assert not any(s.get("ports") for n, s in merged["services"].items() if n != "caddy")
    # The API still waits for the migration AND for the certificate helper.
    assert set(merged["services"]["api"]["depends_on"]) == {"migrate", "rehearsal-ca"}


# --- the smoke test -----------------------------------------------------------------------------


def expectations() -> list[str]:
    """The `expect "what" "wanted" "$(code ...)"` lines of the smoke test: what it asserts."""
    return [line for line in script_text_of(SMOKE).splitlines() if line.startswith("expect ")]


@pytest.mark.parametrize(
    ("wanted", "address"),
    [
        ('"308"', "$HTTP"),  # http -> https
        ('"200"', "/api/v1/health"),  # the API answers through the proxy over HTTPS
        ('"401"', "/api/v1/leads"),  # protected: a token is needed
        ('"404"', "/docs"),  # the API documentation is off...
        ('"404"', "/openapi.json"),
        ('"404"', "/api/v1/internal/metrics"),  # ...and the metrics are hidden at the edge
        ('"413"', "/api/v1/leads"),  # the upload limit
        ('"403"', "/admin/"),  # the administration console is closed...
        ('"403"', "/realms/master/"),  # ...and so is the master realm
    ],
)
def test_the_smoke_test_really_asserts_each_thing_the_rehearsal_is_for(
    wanted: str, address: str
) -> None:
    assert any(wanted in line and address in line for line in expectations()), (wanted, address)


def test_the_admin_console_is_checked_closed_then_opened_for_an_address_then_closed_again() -> None:
    lines = script_text_of(SMOKE).splitlines()
    opening = next(i for i, line in enumerate(lines) if line.startswith("ADMIN_ALLOWED_IPS="))
    closed = [i for i, line in enumerate(lines) if '"403"' in line and "/admin/" in line]
    assert any(i < opening for i in closed), "closed before the allow-list is given an address"
    assert any(i > opening for i in closed), "and closed again after it is emptied"
    assert any(line.startswith("opened=") and "/admin/" in line for line in lines[opening:])
    assert any('!= "403"' in line for line in lines[opening:]), "it really opens for an allowed one"


def test_the_smoke_test_also_looks_inside_the_answers() -> None:
    lines = [line for line in script_text_of(SMOKE).splitlines() if line.startswith("contains ")]
    for needle in (
        '"database":"ok"',
        '"vector":"ok"',
        "Strict-Transport-Security",
        "nosniff",
        '"issuer"',
        "https://$LOGIN_HOST/realms/crm",  # the issuer is the public https name of the sign-in host
    ):
        assert any(needle in line for line in lines), needle


def test_the_smoke_test_proves_it_can_tell_a_broken_trust_from_a_working_one() -> None:
    # An API that cannot reach the sign-in keys over HTTPS answers 503, one that can answers 401.
    # The script must make the API unable to trust the throwaway authority on purpose, and see 503.
    lines = script_text_of(SMOKE).splitlines()
    broken, restored = lines.index("break_trust"), lines.index("restore_trust")  # the CALLS
    assert broken < restored
    between = lines[broken:restored]
    assert any('"503"' in line and line.startswith("expect ") for line in between), (
        "503 while broken"
    )
    before = [line for line in lines[:broken] if line.startswith("expect ") and "auth" in line]
    after = [line for line in lines[restored:] if line.startswith("expect ") and "auth" in line]
    assert any('"401"' in line for line in before), "401 before the trust is taken away"
    assert any('"401"' in line for line in after), "and 401 again once it is restored"
    text = "\n".join(lines)
    # A missing file would crash the API at start; an ordinary certificate list makes it start and
    # then fail to trust the throwaway authority, which is what has to be seen (503).
    assert "/etc/ssl/certs/ca-certificates.crt" in text and "/nonexistent" not in text


def test_the_smoke_test_stops_on_a_failed_check_and_prints_a_verdict() -> None:
    text = script_text_of(SMOKE)
    assert "SMOKE TEST PASSED" in text and "SMOKE TEST FAILED" in text
    assert re.search(r"^set -euo pipefail$", text, flags=re.M)


def script_text_of(path: Path) -> str:
    return code(path.read_text(encoding="utf-8"))


def test_the_new_scripts_have_valid_syntax() -> None:
    bash = working_bash()
    if bash is None:
        pytest.skip("no working bash on this machine")
    for path in (SMOKE, SERVER_CHECK):
        assert subprocess.run([bash, "-n", str(path)], capture_output=True).returncode == 0, path


# --- the server check and the hardening guide ---------------------------------------------------


def test_the_server_check_looks_at_what_the_guide_asks_for() -> None:
    text = script_text_of(SERVER_CHECK)
    for item in (
        "ufw",
        "PasswordAuthentication",
        "PermitRootLogin",
        "unattended-upgrades",
        ".env",
        "swap",
        "docker compose",
        "last_success",
        "timedatectl",
        "df ",
    ):
        assert item in text, item


def test_the_server_check_changes_nothing_and_prints_no_secret() -> None:
    text = script_text_of(SERVER_CHECK)
    for forbidden in ("ufw enable", "ufw allow", "systemctl", "sed -i", "chmod ", "rm ", "apt "):
        assert forbidden not in text, forbidden
    assert not re.search(r"cat[^\n]*\.env|echo[^\n]*(PASSWORD|SECRET)", text)
    assert re.search(r"^set -uo pipefail$", text, flags=re.M), (
        "it reports every problem, it does not stop"
    )


def test_the_hardening_guide_covers_the_whole_list() -> None:
    text = HARDENING.read_text(encoding="utf-8")
    for heading in (
        "Firewall",
        "SSH",
        "Updates",
        "Docker",
        "Time",
        "Swap",
        "Disk",
        "The .env file",
        "DNS",
        "Checking it",
    ):
        assert heading in text, heading
    for command in (
        "ufw",
        "PasswordAuthentication no",
        "PermitRootLogin no",
        "unattended-upgrades",
    ):
        assert command in text, command
    assert "bin/server-check.sh" in text


def test_the_guide_is_linked_from_the_readme_and_the_adr_index_knows_the_folder() -> None:
    readme = (FOLDER / "README.md").read_text(encoding="utf-8")
    assert "one-host-hardening.md" in readme and "rehearsal/" in readme

# ruff: noqa: S603, S607, S104 - runs docker/git by name on purpose; "0.0.0.0" is test input
"""The one-server deployment files (ADR 0021, step OH1).

Nothing here starts Docker. The tests read ``deploy/one-host`` and check the promises of the ADR on
the files themselves: only the reverse proxy is reachable from outside, the database never is, the
API never holds the schema owner's password, no development value or placeholder can reach
production, and the two small tools that write and check the server's ``.env`` do what they say.
"""

import importlib.util
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]  # no stubs; used only to read the compose file

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "deploy" / "one-host"
COMPOSE = FOLDER / "docker-compose.yml"
CADDYFILE = FOLDER / "Caddyfile"
ENV_EXAMPLE = FOLDER / ".env.example"
INIT = FOLDER / "postgres" / "init"

SERVICES = {"postgres", "migrate", "api", "worker", "keycloak", "caddy", "backup"}
LONG_RUNNING = {"postgres", "api", "worker", "keycloak", "caddy", "backup"}


def load_tool(name: str) -> ModuleType:
    path = FOLDER / "bin" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"one_host_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


make_env = load_tool("make_env")
check_env = load_tool("check_env")


def compose() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    return data


def services() -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = compose()["services"]
    return found


def env_names() -> set[str]:
    names = set()
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^#?\s*([A-Z][A-Z0-9_]+)=", line)
        if match:
            names.add(match.group(1))
    return names


def environment_of(service: str) -> dict[str, str]:
    raw = services()[service].get("environment", {})
    if isinstance(raw, list):
        return dict(item.split("=", 1) for item in raw)
    return {k: str(v) for k, v in raw.items()}


HOSTS = {
    "api_host": "api.acme-realty.in",
    "login_host": "login.acme-realty.in",
    "web_url": "https://crm.acme-realty.in",
    "acme_email": "owner@acme-realty.in",
    "mail_from_address": "no-reply@acme-realty.in",
}


def fresh() -> str:
    return str(make_env.generate(**HOSTS))


def filled(text: str) -> str:
    """What the owner does by hand: replace the CHANGE_ME lines of the outside services."""
    values = {
        "CRM_FILES_S3_ENDPOINT": "s3.eu-central-003.backblazeb2.com:443",
        "CRM_FILES_S3_ACCESS_KEY": "0123456789abcdef01234567",
        "CRM_FILES_S3_SECRET_KEY": "K003xYzAbCdEfGhIjKlMnOpQrStUvWxYz012345",
        "CRM_FILES_S3_BUCKET": "acme-crm-files",
        "BACKUP_S3_ENDPOINT": "s3.eu-central-003.backblazeb2.com:443",
        "BACKUP_S3_BUCKET": "acme-crm-backups",
        "BACKUP_S3_ACCESS_KEY": "0123456789abcdef01234568",
        "BACKUP_S3_SECRET_KEY": "K003aBcDeFgHiJkLmNoPqRsTuVwXyZ98765432",
        "BACKUP_AGE_PUBLIC_KEY": BACKUP_PUBLIC_KEY,
        "CRM_SMTP_HOST": "smtp.eu.mailgun.org",
        "CRM_SMTP_USERNAME": "postmaster@acme-realty.in",
        "CRM_SMTP_PASSWORD": "mailgun-7f3a9c1e5b2d4086a1c3e5f70912b4d6",
    }
    out = []
    for line in text.splitlines():
        name = line.split("=", 1)[0]
        out.append(f"{name}={values[name]}" if name in values and "CHANGE_ME" in line else line)
    return "\n".join(out) + "\n"


def with_value(text: str, name: str, value: str) -> str:
    return re.sub(rf"^{name}=.*$", f"{name}={value}", text, flags=re.M)


# --- the compose file: who can be reached from outside ------------------------------------------


def test_the_project_name_differs_from_the_development_stack() -> None:
    dev = yaml.safe_load((ROOT / "infrastructure" / "docker-compose.yml").read_text("utf-8"))
    dev_name = dev.get("name") or "infrastructure"
    assert compose()["name"] not in {dev_name, "crm-lead", "infrastructure"}
    assert "postgres_data" in compose()["volumes"]  # named volumes are prefixed by the name


def test_the_stack_has_exactly_the_services_of_the_adr() -> None:
    assert set(services()) == SERVICES


def test_only_the_reverse_proxy_publishes_ports_and_only_web_ones() -> None:
    published = {name: s.get("ports", []) for name, s in services().items() if s.get("ports")}
    assert set(published) == {"caddy"}
    for port in published["caddy"]:
        assert re.fullmatch(r"(0\.0\.0\.0:)?(80|443):(80|443)(/tcp|/udp)?", str(port)), port


@pytest.mark.parametrize("name", sorted(SERVICES))
def test_no_service_is_privileged_or_on_the_hosts_network(name: str) -> None:
    service = services()[name]
    assert not service.get("privileged")
    assert service.get("network_mode") != "host"
    assert not service.get("cap_add")
    assert "/var/run/docker.sock" not in str(service.get("volumes", []))


@pytest.mark.parametrize("name", sorted(SERVICES))
def test_every_service_is_limited_and_logs_are_rotated(name: str) -> None:
    service = services()[name]
    assert service.get("mem_limit"), f"{name} has no memory limit"
    assert service["logging"]["options"]["max-size"], f"{name} logs are not rotated"


@pytest.mark.parametrize("name", sorted(LONG_RUNNING))
def test_long_running_services_restart_by_themselves(name: str) -> None:
    assert services()[name]["restart"] == "unless-stopped"


def test_the_migration_job_runs_once_and_does_not_restart() -> None:
    assert services()["migrate"]["restart"] == "no"


@pytest.mark.parametrize("name", ["postgres", "keycloak", "caddy", "worker", "backup"])
def test_services_without_a_built_in_check_declare_one(name: str) -> None:
    assert services()[name]["healthcheck"]["test"]


def test_the_worker_is_judged_by_its_heartbeat_not_by_the_apis_web_port() -> None:
    # The image's own check asks port 8000, where only the API listens: inherited by the worker it
    # would show "unhealthy" for a worker that works. The worker writes service_heartbeats.
    test = " ".join(services()["worker"]["healthcheck"]["test"])
    assert "service_heartbeats" in test and "8000" not in test
    assert "CRM_DATABASE_URL" in test, "it must use the restricted app role, not the owner"


def test_the_api_image_has_a_health_check_of_its_own() -> None:
    assert "HEALTHCHECK" in (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")


def test_images_are_pinned_and_built_ones_are_tagged() -> None:
    for name, service in services().items():
        image = service.get("image", "")
        assert image, f"{name} has no image name"
        assert ":" in image and not image.endswith(":latest"), f"{name}: {image}"


def test_start_order_is_database_then_migration_then_the_app() -> None:
    s = services()
    assert s["migrate"]["depends_on"]["postgres"]["condition"] == "service_healthy"
    for name in ("api", "worker"):
        assert s[name]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert s["keycloak"]["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert "api" in s["caddy"]["depends_on"] and "keycloak" in s["caddy"]["depends_on"]


# --- the compose file: secrets and roles --------------------------------------------------------


def test_only_the_migration_job_gets_the_schema_owners_password() -> None:
    for name in SERVICES - {"migrate", "postgres"}:
        text = str(services()[name])
        assert "CRM_MIGRATION_DATABASE_URL" not in text and "CRM_DB_OWNER_PASSWORD" not in text, (
            name
        )
    assert "crm_owner" in environment_of("migrate")["CRM_MIGRATION_DATABASE_URL"]


def test_the_api_and_the_worker_use_the_restricted_app_role_on_the_crm_database() -> None:
    for name in ("api", "worker"):
        url = environment_of(name)["CRM_DATABASE_URL"]
        assert url.startswith("postgresql+psycopg://crm_app:") and url.endswith(
            "@postgres:5432/crm"
        )


def test_the_api_runs_in_production_mode_with_the_docs_off() -> None:
    for name in ("api", "worker"):
        env = environment_of(name)
        assert env["CRM_ENVIRONMENT"] == "production" and env["CRM_DOCS_ENABLED"] == "false"
        assert env["CRM_FILES_S3_SECURE"] == "true" and env["CRM_SMTP_STARTTLS"] == "true"
        assert env["CRM_OIDC_ISSUER"].startswith("https://")


def test_the_ai_and_website_chat_settings_reach_the_api_and_the_worker() -> None:
    # Found on the first real server: only the keys were passed, so the provider, the model and the
    # website chat could not be chosen in .env at all.
    for name in ("api", "worker"):
        env = environment_of(name)
        assert env["CRM_AI_PROVIDER"] == "${CRM_AI_PROVIDER:-anthropic}"
        assert env["CRM_DEEPSEEK_BASE_URL"].endswith(":-https://api.deepseek.com}")
        assert env["CRM_DEEPSEEK_MODEL"] == "${CRM_DEEPSEEK_MODEL:-deepseek-chat}"
        assert env["CRM_DEEPSEEK_FALLBACK_MODELS"] == "${CRM_DEEPSEEK_FALLBACK_MODELS:-}"
        # Found on staging (2026-11-08): a free "thinking" model used all 1024 output tokens before
        # writing the account brief, and the limit could not be raised on the server.
        assert env["CRM_ASSISTANT_MAX_TOKENS"] == "${CRM_ASSISTANT_MAX_TOKENS:-1024}"
        # Go-live check (2026-11-09): the browser's own speech engine sends spoken words to
        # Google/Apple/Microsoft, so on the server it is OFF unless the owner switches it on.
        assert env["CRM_VOICE_BROWSER_ENGINE"] == "${CRM_VOICE_BROWSER_ENGINE:-false}"
        # The website chat stays off unless the owner sets both values.
        assert env["CRM_PUBLIC_CHAT_TENANT_SLUG"] == "${CRM_PUBLIC_CHAT_TENANT_SLUG:-}"
        assert env["CRM_PUBLIC_CHAT_SERVER_KEY"] == "${CRM_PUBLIC_CHAT_SERVER_KEY:-}"
        assert "fake" not in env["CRM_AI_PROVIDER"] + env["CRM_PUBLIC_CHAT_PROVIDER"]


def test_the_compose_file_holds_no_secret_values_only_references() -> None:
    secretish = re.compile(r"(PASSWORD|SECRET|TOKEN|KEY)", re.I)
    for name in SERVICES:
        for key, value in environment_of(name).items():
            if secretish.search(key):
                assert value.startswith("${") or value in {"true", "false"}, f"{name}.{key}"


def test_every_variable_the_compose_file_needs_is_in_the_env_template() -> None:
    needed = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", COMPOSE.read_text(encoding="utf-8")))
    needed |= set(re.findall(r"\{\$([A-Z][A-Z0-9_]*)", CADDYFILE.read_text(encoding="utf-8")))
    assert needed <= env_names(), sorted(needed - env_names())


def test_the_proxy_can_be_reached_by_the_api_under_the_public_names() -> None:
    # Inside the network the public host names point at Caddy, so the API can fetch the sign-in
    # keys over the same HTTPS address the browser uses (no hairpin through the server's own IP).
    aliases = services()["caddy"]["networks"]["crm"]["aliases"]
    assert set(aliases) == {"${API_HOST}", "${LOGIN_HOST}"}


# --- the reverse proxy --------------------------------------------------------------------------


def test_caddy_serves_both_hosts_with_hsts_and_never_the_metrics() -> None:
    text = CADDYFILE.read_text(encoding="utf-8")
    assert "{$API_HOST}" in text and "{$LOGIN_HOST}" in text
    assert "Strict-Transport-Security" in text and "X-Content-Type-Options" in text
    assert "/metrics" in text and "respond @metrics 404" in text
    assert "reverse_proxy api:8000" in text and "reverse_proxy keycloak:8080" in text
    assert "tls internal" not in text and "auto_https off" not in text, "that is for rehearsal only"


def test_the_sign_in_admin_console_is_closed_unless_an_address_is_allowed() -> None:
    text = CADDYFILE.read_text(encoding="utf-8")
    assert "/admin*" in text and "/realms/master*" in text
    assert "{$ADMIN_ALLOWED_IPS:127.0.0.1}" in text, "the default must let nobody in"


def test_uploads_are_limited_to_what_the_app_accepts() -> None:
    assert re.search(r"max_size\s+25MB", CADDYFILE.read_text(encoding="utf-8"))


# --- the database first-start scripts -----------------------------------------------------------


def init_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(INIT.glob("*.sh")))


def test_the_database_scripts_create_the_two_databases_and_no_test_database() -> None:
    text = init_text()
    assert "crm_test" not in text and "CREATE DATABASE crm " in text.replace("crm OWNER", "crm ")
    assert "keycloak" in text and "CREATE EXTENSION IF NOT EXISTS vector" in text


def test_the_app_role_can_never_bypass_row_level_security_or_become_a_superuser() -> None:
    text = init_text()
    assert "BYPASSRLS" in text  # the owner role, for the migration job only
    assert re.search(r"ALTER ROLE :\"owner\" BYPASSRLS", text)
    assert not re.search(r"ALTER ROLE :\"app\"[^;]*(BYPASSRLS|SUPERUSER)", text)
    assert "SUPERUSER" not in text.replace("POSTGRES_USER", "")


def test_the_database_scripts_take_every_password_from_the_environment() -> None:
    for script in INIT.glob("*.sh"):
        text = script.read_text(encoding="utf-8")
        assert not re.search(r"PASSWORD\s+'[^':]", text), script.name
        assert text.startswith("#!/bin/sh") and "set -eu" in text


# --- .env.example -------------------------------------------------------------------------------


def test_the_env_template_has_placeholders_and_no_real_looking_secret() -> None:
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        name = line.split("=", 1)[0]
        if re.match(r"^[A-Z][A-Z0-9_]+=", line) and re.search(
            r"(PASSWORD|SECRET|TOKEN|_KEY)$", name
        ):
            assert line.split("=", 1)[1] in {"", "CHANGE_ME"}, name


def test_env_files_are_ignored_by_git() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "deploy/one-host/.env"], cwd=ROOT, check=False
    )
    assert result.returncode == 0


# --- make_env: writes the server's .env ---------------------------------------------------------

SECRETS = [
    "POSTGRES_PASSWORD",
    "CRM_DB_OWNER_PASSWORD",
    "CRM_DB_APP_PASSWORD",
    "CRM_DB_BACKUP_PASSWORD",
    "KEYCLOAK_DB_PASSWORD",
    "KEYCLOAK_ADMIN_PASSWORD",
    "CRM_WEB_CLIENT_SECRET",
    "CRM_USER_ADMIN_CLIENT_SECRET",
    "CRM_METRICS_TOKEN",
]
BACKUP_PUBLIC_KEY = "age1" + ("qpzry9x8gf2tvdw0s3jn54khce6mua7l" * 2)[:58]


def value_of(text: str, name: str) -> str:
    match = re.search(rf"^{name}=(.*)$", text, flags=re.M)
    assert match, name
    return match.group(1)


def test_every_secret_is_new_long_random_and_different_from_the_others() -> None:
    text = fresh()
    values = [value_of(text, name) for name in SECRETS]
    assert all(len(v) >= 32 for v in values)
    assert all(re.fullmatch(r"[A-Za-z0-9_-]+", v) for v in values), "URL-safe: used inside URLs"
    assert len(set(values)) == len(values)


def test_two_runs_never_give_the_same_secrets() -> None:
    first, second = fresh(), fresh()
    assert all(value_of(first, n) != value_of(second, n) for n in SECRETS)


def test_the_web_apps_secret_is_the_one_keycloak_gets_and_nothing_is_hidden_twice() -> None:
    text = fresh()
    assert (
        text.count("CRM_WEB_CLIENT_SECRET=") == 1
        and text.count("CRM_USER_ADMIN_CLIENT_SECRET=") == 1
    )


def test_addresses_are_derived_from_the_three_names_given() -> None:
    text = fresh()
    assert value_of(text, "API_HOST") == HOSTS["api_host"]
    assert value_of(text, "LOGIN_HOST") == HOSTS["login_host"]
    assert value_of(text, "WEB_URL") == HOSTS["web_url"]
    assert value_of(text, "ADMIN_ALLOWED_IPS") == "127.0.0.1"


def test_the_outside_services_are_left_for_the_owner_to_fill_in() -> None:
    text = fresh()
    for name in (
        "CRM_FILES_S3_ACCESS_KEY",
        "CRM_FILES_S3_SECRET_KEY",
        "CRM_SMTP_PASSWORD",
        "BACKUP_S3_SECRET_KEY",
        "BACKUP_AGE_PUBLIC_KEY",
    ):
        assert value_of(text, name) == "CHANGE_ME"


@pytest.mark.parametrize(
    "bad",
    [
        {"api_host": "localhost"},
        {"api_host": "api.example.com"},
        {"login_host": "10.0.0.5"},
        {"api_host": "https://api.acme-realty.in"},
        {"web_url": "http://crm.acme-realty.in"},
        {"acme_email": "not-an-address"},
        {"api_host": "same.acme-realty.in", "login_host": "same.acme-realty.in"},
    ],
)
def test_make_env_refuses_addresses_that_cannot_work_in_production(bad: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        make_env.generate(**{**HOSTS, **bad})


def test_the_command_line_writes_a_private_file_and_never_prints_a_secret(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / ".env"
    args = [
        "--api-host", HOSTS["api_host"], "--login-host", HOSTS["login_host"],
        "--web-url", HOSTS["web_url"], "--acme-email", HOSTS["acme_email"],
        "--mail-from", HOSTS["mail_from_address"], "--out", str(target),
    ]  # fmt: skip
    assert make_env.main(args) == 0
    written = target.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert not any(value_of(written, name) in out for name in SECRETS)
    assert "CRM_FILES_S3_SECRET_KEY" in out, "it tells what is left to fill in"
    if sys.platform != "win32":
        assert target.stat().st_mode & 0o077 == 0, "readable by the owner only"


def test_it_will_not_overwrite_an_existing_file_without_being_told_to(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("KEEP=me\n", encoding="utf-8")
    args = [
        "--api-host", HOSTS["api_host"], "--login-host", HOSTS["login_host"],
        "--web-url", HOSTS["web_url"], "--acme-email", HOSTS["acme_email"],
        "--mail-from", HOSTS["mail_from_address"], "--out", str(target),
    ]  # fmt: skip
    assert make_env.main(args) != 0
    assert target.read_text(encoding="utf-8") == "KEEP=me\n"
    assert make_env.main([*args, "--force"]) == 0


# --- check_env: refuses a file that must not reach production -----------------------------------


def problems(text: str) -> list[str]:
    return list(check_env.check(text))


def test_a_finished_file_passes() -> None:
    assert problems(filled(fresh())) == []


def test_a_fresh_file_fails_until_the_outside_services_are_filled_in() -> None:
    found = problems(fresh())
    assert any("CRM_FILES_S3_SECRET_KEY" in p for p in found)
    assert any("CRM_SMTP_PASSWORD" in p for p in found)


@pytest.mark.parametrize("name", SECRETS)
def test_a_missing_secret_is_refused(name: str) -> None:
    text = re.sub(rf"^{name}=.*\n", "", filled(fresh()), flags=re.M)
    assert any(name in p for p in problems(text))


@pytest.mark.parametrize("name", SECRETS)
@pytest.mark.parametrize(
    "weak",
    [
        "short",
        "CHANGE_ME",
        "password1234567890password1234567890",
        "devdevdevdevdevdevdevdevdevdevdevdev",
        "aB3dE5gH7jK9mN1pQ2sT",  # random-looking but only 20 long: too short for a secret
    ],
)
def test_a_weak_or_development_looking_secret_is_refused(name: str, weak: str) -> None:
    text = with_value(filled(fresh()), name, weak)
    assert any(name in p for p in problems(text)), (name, weak)


def test_the_server_holds_only_the_public_half_of_the_backup_key() -> None:
    text = filled(fresh())
    assert value_of(text, "BACKUP_AGE_PUBLIC_KEY").startswith("age1")
    assert "AGE-SECRET-KEY" not in text and "BACKUP_AGE_PRIVATE" not in text
    assert "AGE-SECRET-KEY" not in ENV_EXAMPLE.read_text(encoding="utf-8")


def test_backups_never_share_a_bucket_with_the_documents() -> None:
    text = with_value(
        filled(fresh()), "BACKUP_S3_BUCKET", value_of(filled(fresh()), "CRM_FILES_S3_BUCKET")
    )
    assert any("BACKUP_S3_BUCKET" in p for p in problems(text))


def test_the_same_secret_used_twice_is_refused() -> None:
    text = filled(fresh())
    text = with_value(text, "CRM_DB_APP_PASSWORD", value_of(text, "CRM_DB_OWNER_PASSWORD"))
    assert any("same" in p.lower() for p in problems(text))


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("API_HOST", "localhost"),
        ("LOGIN_HOST", "login.example.com"),
        ("WEB_URL", "http://crm.acme-realty.in"),
        ("ACME_EMAIL", "nobody"),
        ("CRM_FILES_S3_BUCKET", "CHANGE_ME"),
        (
            "BACKUP_AGE_PUBLIC_KEY",
            "AGE-SECRET-KEY-1QQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ",
        ),
        ("BACKUP_AGE_PUBLIC_KEY", "age1short"),
        ("BACKUP_S3_BUCKET", "acme-crm-files"),
        ("ADMIN_ALLOWED_IPS", "0.0.0.0/0"),
        ("ADMIN_ALLOWED_IPS", "0.0.0.0"),
        ("ADMIN_ALLOWED_IPS", "::/0"),
    ],
)
def test_addresses_and_settings_that_cannot_be_right_are_refused(name: str, value: str) -> None:
    assert problems(with_value(filled(fresh()), name, value)), (name, value)


@pytest.mark.parametrize(
    "line",
    [
        "CRM_ENVIRONMENT=development",
        "CRM_AI_PROVIDER=fake",
        "CRM_PUBLIC_CHAT_PROVIDER=fake",
        "CRM_WEBCHECK_DEMO=true",
        "CRM_DOCS_ENABLED=true",
        "CRM_FILES_S3_SECURE=false",
    ],
)
def test_a_development_setting_is_refused_even_if_someone_adds_it(line: str) -> None:
    assert any(line.split("=")[0] in p for p in problems(filled(fresh()) + line + "\n")), line


def test_the_messages_never_contain_a_secret_value() -> None:
    text = with_value(filled(fresh()), "KEYCLOAK_ADMIN_PASSWORD", "short")
    shown = " ".join(problems(text))
    assert "short" not in shown.replace("too short", "")


def test_it_can_check_a_file_from_the_command_line(tmp_path: Path) -> None:
    good, bad = tmp_path / "good.env", tmp_path / "bad.env"
    good.write_text(filled(fresh()), encoding="utf-8")
    bad.write_text(fresh(), encoding="utf-8")
    assert check_env.main([str(good)]) == 0
    assert check_env.main([str(bad)]) == 1


# --- the real compose parser agrees (only when Docker is available) -----------------------------


def docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "compose", "version"], capture_output=True).returncode == 0


@pytest.fixture
def env_file(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / ".env"
    path.write_text(filled(fresh()), encoding="utf-8")
    yield path


@pytest.mark.skipif(not docker_ready(), reason="Docker is not available")
def test_docker_compose_accepts_the_file_with_a_generated_env(env_file: Path) -> None:
    result = subprocess.run(
        ["docker", "compose", "--env-file", str(env_file), "-f", str(COMPOSE), "config", "-q"],
        capture_output=True,
        text=True,
        cwd=FOLDER,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not docker_ready(), reason="Docker is not available")
def test_docker_compose_refuses_to_start_without_the_env_file() -> None:
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), "config", "-q"],
        capture_output=True,
        text=True,
        cwd=FOLDER,
        env={"PATH": __import__("os").environ["PATH"]},
    )
    assert result.returncode != 0


def test_the_api_and_worker_send_keycloak_admin_calls_inside_the_stack() -> None:
    # The proxy closes https://login.../admin* to the internet; through it the API's admin calls
    # (creating an organisation's first administrator) got 403 on the first real server.
    for name in ("api", "worker"):
        assert environment_of(name).get("CRM_IDENTITY_ADMIN_URL") == "http://keycloak:8080", name


def test_the_proxy_image_is_one_without_the_known_critical_flaws() -> None:
    """Go-live scan (2026-11-09): caddy 2.10.2 had 6 critical and 99 high findings that 2.11.4+
    fixes. The proxy is the only part the internet talks to, so it may not fall behind again."""
    image = services()["caddy"]["image"]
    name, tag = image.split(":")
    major, minor, patch = (int(part) for part in tag.removesuffix("-alpine").split("."))
    assert name == "caddy" and tag.endswith("-alpine")
    assert (major, minor, patch) >= (2, 11, 6)

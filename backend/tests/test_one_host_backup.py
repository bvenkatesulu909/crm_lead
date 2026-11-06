# ruff: noqa: S603, S607 - runs bash by name on purpose, on files of this repository
"""Backups, the restore test and updates of the one-server deployment (ADR 0021, step OH2).

Like ``test_one_host_files.py`` these read the files and check the promises of the ADR on them.
The promises that need a database and an S3 store (a dump that restores, an encrypted copy that
decrypts) were checked for real on a PC and are described in the ADR; they cannot run in every CI
job.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_one_host_files import (
    FOLDER,
    compose,
    environment_of,
    filled,
    fresh,
    problems,
    services,
)

BIN = FOLDER / "bin"
BACKUP = FOLDER / "backup"
INIT = FOLDER / "postgres" / "init"
SCRIPTS = sorted([*BIN.glob("*.sh"), *BACKUP.glob("*.sh")])


def working_bash() -> str | None:
    """A bash that really runs. On Windows the first `bash` on the PATH can be a WSL stub with no
    Linux behind it, so each candidate is tried with a command first."""
    for candidate in (shutil.which("bash"), "C:/Program Files/Git/usr/bin/bash.exe"):
        if candidate and Path(candidate).exists():
            probe = subprocess.run([candidate, "-c", "echo ok"], capture_output=True, text=True)
            if probe.returncode == 0 and probe.stdout.strip() == "ok":
                return candidate
    return None


def script_text(name: str) -> str:
    path = next(p for p in SCRIPTS if p.name == name)
    return path.read_text(encoding="utf-8")


def init_sql() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(INIT.glob("*.sh")))


# --- the scripts ---------------------------------------------------------------------------------


def test_the_scripts_exist() -> None:
    assert {p.name for p in SCRIPTS} >= {
        "backup.sh",
        "backup-loop.sh",
        "restore-test.sh",
        "update.sh",
    }


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_every_script_stops_at_the_first_error_and_has_valid_syntax(script: Path) -> None:
    text = script.read_text(encoding="utf-8")
    assert text.startswith(("#!/bin/sh\n", "#!/bin/bash\n")), script.name
    # server-check.sh must report EVERY problem, so it is the one script without `-e`.
    stops = r"^set -uo pipefail$" if script.name == "server-check.sh" else r"^set -eu(o pipefail)?$"
    assert re.search(stops, text, flags=re.M), script.name
    bash = working_bash()
    if bash is None:
        pytest.skip("no working bash on this machine")
    assert subprocess.run([bash, "-n", str(script)], capture_output=True).returncode == 0


def test_the_server_can_only_encrypt_never_decrypt_a_backup() -> None:
    for script in SCRIPTS:
        text = script.read_text(encoding="utf-8")
        assert "AGE-SECRET-KEY" not in text, script.name
        # The `age` COMMAND (not the ".age" file extension) with a decrypting option.
        decrypting = re.search(
            r"(?:^|[\s;|&(])age\s[^\n]*(\s-d\b|--decrypt|\s-i\b|--identity)", text, flags=re.M
        )
        assert not decrypting, script.name
    assert 'age -r "$BACKUP_AGE_PUBLIC_KEY"' in script_text("backup.sh")


def code(text: str) -> str:
    """A script without its comment lines, and with `\\`-continued lines joined, so that a check
    looks at what runs and one command is one line (a word in a comment proves nothing)."""
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    return re.sub(r"\\\n\s*", " ", "\n".join(lines))


def test_a_backup_is_a_custom_format_dump_made_private_and_checked_before_it_is_trusted() -> None:
    backup = code(script_text("backup.sh"))
    assert "pg_dump" in backup and "-Fc" in backup
    assert re.search(r"^umask 077$", backup, flags=re.M), "files must be private"
    assert 'pg_restore --list "$file" > /dev/null || fail' in backup, "readable before trusted"
    assert re.search(r"s3api head-object .*--query ContentLength", backup), "the upload is measured"
    assert '[ "$remote" = "$size" ] || fail' in backup, "...and compared with the file"


def test_a_backup_counts_as_good_only_after_everything_in_it_worked() -> None:
    backup = code(script_text("backup.sh"))
    writes = [m.start() for m in re.finditer(r"> /backups/last_success", backup)]
    assert len(writes) == 1, "exactly one place says 'this was a good backup'"
    assert writes[0] > backup.index("\ndone\n"), "...and it is after both databases are done"
    assert writes[0] > backup.index("find /backups/local"), "...and after the clean-up"


def test_a_command_given_to_the_backup_service_runs_instead_of_the_nightly_loop() -> None:
    # Found by really running it: the image's entrypoint is the nightly loop, so
    # `docker compose run --rm backup /scripts/backup.sh` (the documented way to back up now)
    # started a second loop and hung. The entrypoint must run a command it is given.
    loop = script_text("backup-loop.sh")
    guard = re.search(r'^if \[ "\$#" -gt 0 \]; then\n\s+exec "\$@"\nfi$', loop, flags=re.M)
    assert guard, "backup-loop.sh must exec its arguments when it has any"
    assert guard.start() < loop.index("while true"), "the guard comes before the loop"


@pytest.mark.parametrize("name", ["restore-test.sh", "update.sh"])
def test_host_scripts_survive_git_bash_on_windows(name: str) -> None:
    # Found by really running restore-test.sh from Git Bash: it rewrote "/backups/..." into a
    # Windows path before docker saw it. On the Linux server the variable does nothing.
    assert "export MSYS_NO_PATHCONV=1" in script_text(name)


def test_the_quiet_option_is_only_given_to_the_commands_that_know_it() -> None:
    # Found by really running the backup: `aws s3 cp` accepts --only-show-errors, but the low-level
    # `aws s3api head-object` does not and fails with "Unknown options".
    backup = code(script_text("backup.sh"))
    for line in backup.splitlines():
        if "s3api" in line:
            assert "--only-show-errors" not in line, line
    wrapper = re.search(r"^s3\(\) \{\n(.*?)^\}", backup, flags=re.M | re.S)
    assert wrapper and "--only-show-errors" not in wrapper.group(1)
    assert re.search(r"s3 s3 cp --only-show-errors", backup)


def test_nothing_deletes_from_the_backup_bucket_prints_a_secret_or_traces_commands() -> None:
    for script in SCRIPTS:
        text = script.read_text(encoding="utf-8")
        assert not re.search(r"\bs3 rm\b|\bs3api delete|--delete\b", text), script.name
        assert not re.search(r"echo[^\n]*\$\{?[A-Z_]*(PASSWORD|SECRET|ACCESS_KEY)", text), (
            script.name
        )
        assert "set -x" not in text and "set -o xtrace" not in text, script.name


def test_old_local_copies_go_after_fourteen_days_and_only_on_the_server() -> None:
    find = next(
        line for line in code(script_text("backup.sh")).splitlines() if line.startswith("find ")
    )
    assert find.startswith("find /backups/local ")
    assert "-name '*.dump' -mtime +14" in find, "dumps: after 14 days"
    assert "-name '*.age' -mtime +1 " in find, "half-finished encrypted leftovers: after a day"
    assert find.endswith("-delete")
    assert "-mtime +9" not in find.replace("+14", ""), "no second, longer age"


def test_the_restore_check_uses_a_scratch_database_and_removes_it() -> None:
    text = script_text("restore-test.sh")
    assert "createdb" in text and "dropdb" in text and "trap" in text
    assert "pg_restore" in text and "relforcerowsecurity" in text and "vector" in text
    assert "alembic_version" in text
    assert not re.search(r"dropdb[^\n]*\bcrm\b(?!_)", text), "never the live database"


def test_the_update_backs_up_then_builds_then_migrates_then_starts_and_names_the_way_back() -> None:
    text = code(script_text("update.sh"))
    assert text.index("bin/check_env.py") < text.index("dc run"), "settings are checked first"
    steps = [
        text.index("dc run --rm backup /scripts/backup.sh"),
        text.index("dc build"),
        text.index("dc run --rm migrate"),
        text.index("dc up -d" + chr(10)),
    ]
    assert steps == sorted(steps), "backup, build, migrate, start - in that order"
    assert "restore" in text.lower() and "previous" in text.lower()


# --- the database role and the service ------------------------------------------------------------


def test_the_database_has_a_backup_role_that_reads_everything_and_changes_nothing() -> None:
    text = init_sql()
    assert re.search(r'CREATE ROLE :"backup" LOGIN', text)
    assert re.search(r'ALTER ROLE :"backup" BYPASSRLS', text), "pg_dump must see every row"
    assert re.search(r'GRANT pg_read_all_data TO :"backup"', text)
    assert not re.search(r'ALTER ROLE :"backup"[^;]*(SUPERUSER|CREATEROLE|CREATEDB)', text)
    assert "pg_write_all_data" not in text


def test_the_backup_service_is_private_and_never_holds_a_stronger_database_password() -> None:
    service = services()["backup"]
    assert not service.get("ports")
    env = environment_of("backup")
    assert env["PGUSER"] == "crm_backup" and "CRM_DB_BACKUP_PASSWORD" in env["PGPASSWORD"]
    text = str(service)
    for forbidden in ("POSTGRES_PASSWORD", "CRM_DB_OWNER_PASSWORD", "CRM_DB_APP_PASSWORD"):
        assert forbidden not in text
    assert "BACKUP_AGE_PUBLIC_KEY" in env and not any("PRIVATE" in key for key in env)
    assert env["BACKUP_S3_SECURE"] == "${BACKUP_S3_SECURE:-true}"


def test_the_backups_survive_an_update() -> None:
    assert "backups" in compose()["volumes"]
    assert any(str(v).startswith("backups:") for v in services()["backup"]["volumes"])


def test_the_backup_is_unhealthy_when_a_night_has_been_missed() -> None:
    check = " ".join(services()["backup"]["healthcheck"]["test"])
    assert "last_success" in check


def test_the_backup_settings_cannot_be_turned_to_plain_http() -> None:
    assert problems(filled(fresh()) + "BACKUP_S3_SECURE=false\n")
    assert problems(filled(fresh()) + "BACKUP_S3_SECURE=true\n") == []


def test_the_backup_upload_works_with_google_cloud_storage() -> None:
    # Found on the first real server (2026-11-06): AWS CLI 2.23+ sends a new kind of checksum by
    # default, which Google Cloud Storage's S3 interface refuses ("SignatureDoesNotMatch ...
    # Invalid argument"). Asking for checksums only "when required" works there and on AWS,
    # Backblaze and MinIO alike.
    backup = code(script_text("backup.sh"))
    assert re.search(r"^AWS_REQUEST_CHECKSUM_CALCULATION=when_required$", backup, flags=re.M)
    assert re.search(r"^AWS_RESPONSE_CHECKSUM_VALIDATION=when_required$", backup, flags=re.M)
    exported = re.search(r"^export (.+)$", backup, flags=re.M)
    assert exported is not None
    for name in ("AWS_REQUEST_CHECKSUM_CALCULATION", "AWS_RESPONSE_CHECKSUM_VALIDATION"):
        assert name in exported.group(1).split(), name

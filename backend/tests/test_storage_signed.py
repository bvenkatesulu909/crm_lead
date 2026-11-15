"""Signed links in the file store (ADR 0025, step DU1) - the pure part: names, keys, the in-memory
store's rules, and a store that is not configured. The same behaviour against the real SeaweedFS
is in tests/test_storage_seaweedfs.py (opt-in)."""

import uuid

import pytest

from app.core.storage import (
    DOWNLOAD_LINK_LIFETIME,
    PENDING_PREFIX,
    UPLOAD_LINK_LIFETIME,
    FileStoreUnavailableError,
    MemoryFileStore,
    StoredFileMissingError,
    UnconfiguredFileStore,
    content_disposition,
    object_key,
    pending_key,
)

TENANT = uuid.UUID("11111111-1111-4111-8111-111111111111")
UPLOAD = uuid.UUID("22222222-2222-4222-8222-222222222222")


# --- the "save as" name------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "plain"),
    [
        ("brochure.pdf", "brochure.pdf"),
        ('a"b.pdf', "a_b.pdf"),
        ("evil\r\nX-Injected: 1.pdf", "evil__X-Injected_ 1.pdf"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\x\\report.pdf", "report.pdf"),
        ("", "file"),
        ("   ", "file"),
    ],
)
def test_the_save_as_name_is_plain_and_cannot_break_the_header(name: str, plain: str) -> None:
    value = content_disposition(name)
    assert value.startswith(f"attachment; filename=\"{plain}\"; filename*=UTF-8''")
    assert "\r" not in value and "\n" not in value
    assert value.count('"') == 2  # only the two quotes around the plain name


def test_a_name_in_another_script_keeps_its_letters_in_the_utf8_form() -> None:
    value = content_disposition("\u0c05\u0c28\u0c02\u0c24\u0c2a\u0c41\u0c30\u0c02.pdf")
    assert "filename*=UTF-8''%E0%B0%85" in value


def test_a_very_long_name_is_cut() -> None:
    value = content_disposition("x" * 500 + ".pdf")
    assert len(value) < 800


# --- keys--------------------------------------------------------------------------------------


def test_a_pending_key_is_apart_from_every_document_key() -> None:
    key = pending_key(TENANT, UPLOAD)
    assert key == f"pending/{TENANT}/{UPLOAD}"
    assert key.startswith(PENDING_PREFIX)
    assert not object_key(TENANT, "accounts", UPLOAD, UPLOAD).startswith(PENDING_PREFIX)


def test_the_link_lifetimes_are_the_accepted_ones() -> None:
    assert UPLOAD_LINK_LIFETIME.total_seconds() == 300
    assert DOWNLOAD_LINK_LIFETIME.total_seconds() == 60


# --- the in-memory store behaves like a real one-----------------------------------------------


def test_a_signed_upload_names_one_key_one_type_and_a_size() -> None:
    store = MemoryFileStore()
    key = pending_key(TENANT, UPLOAD)
    signed = store.signed_upload(key, content_type="application/pdf", max_bytes=100)
    assert signed.fields["key"] == key and signed.fields["Content-Type"] == "application/pdf"
    assert store.signed_uploads[key] == ("application/pdf", 100)


def test_the_store_refuses_what_was_not_signed() -> None:
    store = MemoryFileStore()
    key = pending_key(TENANT, UPLOAD)
    store.signed_upload(key, content_type="application/pdf", max_bytes=10)
    assert store.browser_upload(pending_key(TENANT, uuid.uuid4()), b"x") is False  # other key
    assert store.browser_upload(key, b"x" * 11) is False  # bigger than signed
    assert store.browser_upload(key, b"") is False  # empty
    assert key not in store.objects
    assert store.browser_upload(key, b"%PDF-1") is True
    assert store.stat(key).size == 6 and store.stat(key).content_type == "application/pdf"


def test_stat_of_a_missing_object_says_so() -> None:
    with pytest.raises(StoredFileMissingError):
        MemoryFileStore().stat("pending/x")


def test_a_stored_save_as_name_is_kept_and_removed_with_the_object() -> None:
    store = MemoryFileStore()
    store.put("tenant/x/y", b"data", "application/pdf", download_name="brochure.pdf")
    assert store.download_names["tenant/x/y"] == "brochure.pdf"
    assert "name=brochure.pdf" in store.signed_download("tenant/x/y", file_name="brochure.pdf")
    store.delete("tenant/x/y")
    assert "tenant/x/y" not in store.download_names


def test_a_signed_upload_must_allow_at_least_one_byte() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        MemoryFileStore().signed_upload("pending/x", content_type="text/plain", max_bytes=0)


# --- a server without a file store-------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda s: s.stat("pending/x"),
        lambda s: s.signed_upload("pending/x", content_type="application/pdf", max_bytes=10),
        lambda s: s.signed_download("tenant/x", file_name="a.pdf"),
        lambda s: s.put("tenant/x", b"x", "application/pdf", download_name="a.pdf"),
    ],
)
def test_without_a_file_store_every_call_answers_unavailable(call) -> None:  # noqa: ANN001
    with pytest.raises(FileStoreUnavailableError):
        call(UnconfiguredFileStore())

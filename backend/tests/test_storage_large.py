"""The file store's extras for large recordings (ADR 0030, step CA1): copying inside the store,
reading only the first bytes, and a per-call size limit. The in-memory store is the reference."""

import pytest

from app.core.storage import (
    FileStoreUnavailableError,
    MemoryFileStore,
    StoredFileMissingError,
    UnconfiguredFileStore,
)


def test_a_file_is_copied_inside_the_store_and_the_original_stays() -> None:
    store = MemoryFileStore()
    store.put("pending/a", b"audio bytes", "audio/mpeg")
    store.copy("pending/a", "tenant/t/calls/l/c")
    assert store.get("tenant/t/calls/l/c") == b"audio bytes"
    assert store.stat("tenant/t/calls/l/c").content_type == "audio/mpeg"
    assert store.get("pending/a") == b"audio bytes"


def test_copying_a_missing_file_says_so() -> None:
    with pytest.raises(StoredFileMissingError):
        MemoryFileStore().copy("pending/none", "tenant/x")


def test_only_the_first_bytes_are_read() -> None:
    store = MemoryFileStore()
    store.put("k", b"0123456789", "application/octet-stream")
    assert store.read_head("k", 4) == b"0123"
    assert store.read_head("k", 100) == b"0123456789"
    with pytest.raises(StoredFileMissingError):
        store.read_head("missing", 4)
    with pytest.raises(ValueError):
        store.read_head("k", 0)


def test_a_signed_upload_may_ask_for_more_than_the_usual_limit() -> None:
    store = MemoryFileStore()
    signed = store.signed_upload(
        "pending/x", content_type="audio/mpeg", max_bytes=90_000_000, hard_limit=100_000_000
    )
    assert signed.fields["key"] == "pending/x"
    assert store.signed_uploads["pending/x"] == ("audio/mpeg", 90_000_000)
    with pytest.raises(ValueError):
        store.signed_upload(
            "pending/y", content_type="audio/mpeg", max_bytes=100_000_001, hard_limit=100_000_000
        )


def test_an_unconfigured_store_refuses_the_new_calls_too() -> None:
    store = UnconfiguredFileStore()
    with pytest.raises(FileStoreUnavailableError):
        store.copy("a", "b")
    with pytest.raises(FileStoreUnavailableError):
        store.read_head("a", 4)

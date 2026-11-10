"""Signed links against a REAL S3 store (ADR 0025, step DU1). Opt-in: needs the development file
store (SeaweedFS, `docker compose up -d` in infrastructure/) and its keys in the API's settings.

    set CRM_RUN_STORE_TESTS=1 && pytest tests/test_storage_seaweedfs.py

Every test uses its own throwaway key under pending/storage-test/ and deletes it."""

import os
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from urllib.parse import urlsplit

import pytest

from app.core.config import Settings
from app.core.storage import S3FileStore, SignedUpload, StoredFileMissingError

pytestmark = pytest.mark.skipif(
    os.environ.get("CRM_RUN_STORE_TESTS") != "1",
    reason="set CRM_RUN_STORE_TESTS=1 with the development file store running",
)


def settings(**overrides: object) -> Settings:
    found = Settings(**overrides)  # type: ignore[arg-type]  # reads backend/.env like the API
    if not found.files_configured:
        pytest.skip("the file store has no keys in the settings")
    return found


@pytest.fixture
def store() -> S3FileStore:
    return S3FileStore(settings())


@pytest.fixture
def key(store: S3FileStore) -> Iterator[str]:
    name = f"pending/storage-test/{uuid.uuid4().hex}"
    yield name
    store.delete(name)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None  # report a redirect (SeaweedFS refuses with 307), never follow it


_OPENER = urllib.request.build_opener(_NoRedirect)


def post(signed: SignedUpload, data: bytes, **field_changes: str) -> int:
    """POST the way a browser form does: every signed field, then the file last."""
    fields = {**signed.fields, **field_changes}
    boundary = uuid.uuid4().hex
    body = b""
    for name, value in fields.items():
        body += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
        ).encode()
    body += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="f"\r\n'
        f"Content-Type: {fields['Content-Type']}\r\n\r\n"
    ).encode()
    body += data + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(  # noqa: S310 - our own signed http(s) link
        signed.url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with _OPENER.open(request, timeout=30) as response:
            return int(response.status)
    except urllib.error.HTTPError as error:
        return error.code


def test_a_file_within_the_signed_size_is_stored(store: S3FileStore, key: str) -> None:
    signed = store.signed_upload(key, content_type="application/pdf", max_bytes=100)
    assert post(signed, b"%PDF-1.4 small") in (200, 201, 204)
    found = store.stat(key)
    assert (found.size, found.content_type) == (14, "application/pdf")


def test_the_store_itself_refuses_a_file_over_the_signed_size(store: S3FileStore, key: str) -> None:
    signed = store.signed_upload(key, content_type="application/pdf", max_bytes=100)
    assert post(signed, b"%PDF" + b"x" * 500) not in (200, 201, 204)
    with pytest.raises(StoredFileMissingError):
        store.stat(key)


def test_the_link_cannot_be_used_for_another_key(store: S3FileStore, key: str) -> None:
    signed = store.signed_upload(key, content_type="application/pdf", max_bytes=100)
    other = f"pending/storage-test/{uuid.uuid4().hex}"
    # Refused: Google Cloud Storage answers 400, SeaweedFS 307 - either way NOTHING is stored.
    assert post(signed, b"%PDF-1.4", key=other) not in (200, 201, 204)
    with pytest.raises(StoredFileMissingError):
        store.stat(other)


def test_the_link_cannot_be_used_for_another_type(store: S3FileStore, key: str) -> None:
    signed = store.signed_upload(key, content_type="application/pdf", max_bytes=100)
    assert post(signed, b"<html>", **{"Content-Type": "text/html"}) not in (200, 201, 204)
    with pytest.raises(StoredFileMissingError):
        store.stat(key)


def test_a_signed_download_gives_the_bytes_with_the_stored_name(
    store: S3FileStore, key: str
) -> None:
    store.put(key, b"%PDF-1.4 download", "application/pdf", download_name="Brochure 2026.pdf")
    url = store.signed_download(key, file_name="Brochure 2026.pdf")
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
        assert response.read() == b"%PDF-1.4 download"
        assert 'filename="Brochure 2026.pdf"' in response.headers["Content-Disposition"]


def test_a_large_file_keeps_its_stored_name(store: S3FileStore, key: str) -> None:
    # Above 5 MB the client used to split the upload into parts, and SeaweedFS dropped the
    # stored "save as" name: a 15 MB download was named after its key (found by the DU4 journey).
    data = b"%PDF-1.4 " + b" " * (6 * 1024 * 1024)
    store.put(key, data, "application/pdf", download_name="Big brochure.pdf")
    url = store.signed_download(key, file_name="Big brochure.pdf")
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
        assert len(response.read()) == len(data)
        assert 'filename="Big brochure.pdf"' in response.headers["Content-Disposition"]


def test_a_tampered_download_link_is_refused(store: S3FileStore, key: str) -> None:
    store.put(key, b"secret", "application/pdf")
    url = store.signed_download(key, file_name="a.pdf")
    other = url.replace(key.rsplit("/", 1)[1], uuid.uuid4().hex)
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(other, timeout=30)  # noqa: S310
    assert refused.value.code == 403


def test_links_are_signed_for_the_address_the_browser_uses() -> None:
    base = settings()
    host, port = base.files_s3_endpoint.rsplit(":", 1)
    public = f"{'localhost' if host == '127.0.0.1' else host}:{port}"
    store = S3FileStore(settings(files_s3_public_endpoint=public))
    name = f"pending/storage-test/{uuid.uuid4().hex}"
    try:
        signed = store.signed_upload(name, content_type="application/pdf", max_bytes=100)
        assert urlsplit(signed.url).netloc == public
        assert post(signed, b"%PDF-1.4") in (200, 201, 204)
        assert urlsplit(store.signed_download(name, file_name="a.pdf")).netloc == public
    finally:
        store.delete(name)

"""File storage in an S3-compatible object store (ADR 0005; SeaweedFS locally).

``FileStore`` is a Protocol, so tests use ``MemoryFileStore`` and the running app uses
``S3FileStore``. Nothing else in the code talks to the store directly, which keeps swapping it
(MinIO, AWS S3, …) a settings change.

Every object key starts with ``tenant/{tenant_id}/`` (see ``object_key``) or, for an upload that
has not been checked yet, ``pending/{tenant_id}/`` (see ``pending_key``). Keys are built only from
server-side IDs, never from file names or other client input. Authorization is NOT done here:
callers check permissions and record-level policies first, then read or write bytes.

Signed links (ADR 0025) let a browser send or fetch ONE object straight to or from the store, so
large files never pass through the web app's host. A signed upload is a POST policy that pins the
exact key, the content type and the largest size - the store itself refuses anything bigger. A
signed download opens one object for a minute. Neither carries any account rights.
"""

import io
import logging
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import quote

import urllib3
from fastapi import Request
from minio import Minio
from minio.datatypes import PostPolicy
from minio.error import S3Error
from urllib3.exceptions import HTTPError

from app.core.config import Settings
from app.core.errors import DomainError, NotFoundError

logger = logging.getLogger(__name__)


class FileStoreUnavailableError(DomainError):
    status_code = 503
    code = "files_unavailable"


class StoredFileMissingError(NotFoundError):
    code = "file_not_found"


def object_key(tenant_id: uuid.UUID, area: str, record_id: uuid.UUID, file_id: uuid.UUID) -> str:
    """``tenant/{tenant}/{area}/{record}/{file}`` - the tenant prefix keeps tenants apart."""
    if not area.isidentifier():
        raise ValueError("area must be a simple name such as 'quotes'")
    return f"tenant/{tenant_id}/{area}/{record_id}/{file_id}"


UPLOAD_LINK_LIFETIME = timedelta(minutes=5)
DOWNLOAD_LINK_LIFETIME = timedelta(seconds=60)
PENDING_PREFIX = "pending/"


def pending_key(tenant_id: uuid.UUID, upload_id: uuid.UUID) -> str:
    """``pending/{tenant}/{upload}`` - where a browser puts a file before the server checks it."""
    return f"{PENDING_PREFIX}{tenant_id}/{upload_id}"


def content_disposition(file_name: str) -> str:
    """``attachment`` with a safe "save as" name: a plain ASCII fallback (no quotes, slashes or
    control characters) and the full name in RFC 5987 form for every browser that reads it."""
    base = file_name.replace("\\", "/").rsplit("/", 1)[-1].strip() or "file"
    ascii_name = re.sub(r"[^A-Za-z0-9._ ()-]", "_", base)[:150] or "file"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(base[:150], safe='')}"


@dataclass(frozen=True)
class SignedUpload:
    """What a browser needs to POST one file: the address and the form fields, sent in this order
    and followed by the file as the last field named ``file``."""

    url: str
    fields: dict[str, str]
    expires_at: datetime


@dataclass(frozen=True)
class StoredObject:
    size: int
    content_type: str


class FileStore(Protocol):
    def put(
        self, key: str, data: bytes, content_type: str, *, download_name: str | None = None
    ) -> None:
        """``download_name``: stored on the object, so a download shows that name."""
        ...

    def get(self, key: str) -> bytes:
        """Raises ``StoredFileMissingError`` if there is no such object."""
        ...

    def delete(self, key: str) -> None:
        """Deleting a missing object is not an error (handlers may run twice)."""
        ...

    def stat(self, key: str) -> StoredObject:
        """Size and type without reading the bytes. Raises ``StoredFileMissingError``."""
        ...

    def signed_upload(self, key: str, *, content_type: str, max_bytes: int) -> SignedUpload:
        """A POST policy for exactly this key, type and 1..max_bytes, valid five minutes."""
        ...

    def signed_download(self, key: str, *, file_name: str) -> str:
        """A link that opens this one object for 60 seconds, as an attachment."""
        ...


def _http_client(retries: int) -> urllib3.PoolManager:
    # Short connect timeout and few retries: a store that is down should answer 503 quickly
    # instead of keeping an API request (or the worker) waiting.
    return urllib3.PoolManager(
        timeout=urllib3.Timeout(connect=5, read=30),
        maxsize=10,
        retries=urllib3.Retry(
            total=retries, backoff_factor=0.2, status_forcelist=[500, 502, 503, 504]
        ),
    )


class S3FileStore:
    def __init__(self, settings: Settings, *, retries: int = 2) -> None:
        if settings.files_s3_access_key is None or settings.files_s3_secret_key is None:
            raise ValueError("S3FileStore needs files_s3_access_key and files_s3_secret_key")
        self._client = Minio(
            settings.files_s3_endpoint,
            access_key=settings.files_s3_access_key.get_secret_value(),
            secret_key=settings.files_s3_secret_key.get_secret_value(),
            secure=settings.files_s3_secure,
            http_client=_http_client(retries),
        )
        self._bucket = settings.files_s3_bucket
        self._max_bytes = settings.files_max_bytes
        self._bucket_ready = False
        self._lock = threading.Lock()
        # Links are signed for the address the BROWSER uses (the host is part of the signature).
        self._settings = settings
        self._public_endpoint = settings.files_s3_public_endpoint or settings.files_s3_endpoint
        self._signer: Minio | None = None

    def _signing_client(self) -> Minio:
        """A client for the public address. Signing happens locally; the region is learnt once
        from the store through the API's own address, so the signer never needs the network."""
        if self._signer is None:
            with self._lock:
                if self._signer is None:
                    region = self._client._get_region(self._bucket)  # noqa: SLF001 - no public call
                    settings = self._settings
                    assert settings.files_s3_access_key is not None  # noqa: S101 - checked in init
                    assert settings.files_s3_secret_key is not None  # noqa: S101
                    self._signer = Minio(
                        self._public_endpoint,
                        access_key=settings.files_s3_access_key.get_secret_value(),
                        secret_key=settings.files_s3_secret_key.get_secret_value(),
                        secure=settings.files_s3_secure,
                        region=region,
                    )
        return self._signer

    def _ensure_bucket(self) -> None:
        # Created on first use, so a fresh file store works without a manual setup step.
        if self._bucket_ready:
            return
        with self._lock:
            if not self._bucket_ready:
                if not self._client.bucket_exists(self._bucket):
                    self._client.make_bucket(self._bucket)
                self._bucket_ready = True

    def put(
        self, key: str, data: bytes, content_type: str, *, download_name: str | None = None
    ) -> None:
        if len(data) > self._max_bytes:
            raise ValueError("file is larger than files_max_bytes")
        metadata = (
            {"Content-Disposition": content_disposition(download_name)} if download_name else None
        )
        try:
            self._ensure_bucket()
            self._client.put_object(
                self._bucket,
                key,
                io.BytesIO(data),
                len(data),
                content_type=content_type,
                metadata=metadata,  # type: ignore[arg-type]  # minio's hint is too narrow
                # One request, never a multipart upload: SeaweedFS drops the stored "save as"
                # name of a multipart object. Files are at most files_max_bytes (20 MB), far
                # below S3's 5 GB single-request limit; the client needs at least 5 MiB here.
                part_size=max(self._max_bytes, 5 * 1024 * 1024),
            )
        except (S3Error, HTTPError) as exc:
            logger.warning("file store write failed", extra={"error": type(exc).__name__})
            raise FileStoreUnavailableError("The file store is temporarily unavailable.") from exc

    def get(self, key: str) -> bytes:
        try:
            self._ensure_bucket()
            response = self._client.get_object(self._bucket, key)
            try:
                return response.read(self._max_bytes + 1)[: self._max_bytes]
            finally:
                response.close()
                response.release_conn()
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchObject"):
                raise StoredFileMissingError("The file doesn't exist.") from exc
            logger.warning("file store read failed", extra={"error": exc.code})
            raise FileStoreUnavailableError("The file store is temporarily unavailable.") from exc
        except HTTPError as exc:
            raise FileStoreUnavailableError("The file store is temporarily unavailable.") from exc

    def delete(self, key: str) -> None:
        try:
            self._ensure_bucket()
            self._client.remove_object(self._bucket, key)
        except (S3Error, HTTPError) as exc:
            raise FileStoreUnavailableError("The file store is temporarily unavailable.") from exc

    def stat(self, key: str) -> StoredObject:
        try:
            self._ensure_bucket()
            found = self._client.stat_object(self._bucket, key)
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchObject", "NotFound"):
                raise StoredFileMissingError("The file doesn't exist.") from exc
            raise FileStoreUnavailableError("The file store is temporarily unavailable.") from exc
        except HTTPError as exc:
            raise FileStoreUnavailableError("The file store is temporarily unavailable.") from exc
        return StoredObject(int(found.size or 0), found.content_type or "")

    def signed_upload(self, key: str, *, content_type: str, max_bytes: int) -> SignedUpload:
        if not 1 <= max_bytes <= self._max_bytes:
            raise ValueError("max_bytes must be between 1 and files_max_bytes")
        expires = datetime.now(UTC) + UPLOAD_LINK_LIFETIME
        policy = PostPolicy(self._bucket, expires)
        policy.add_equals_condition("key", key)
        policy.add_equals_condition("Content-Type", content_type)
        policy.add_content_length_range_condition(1, max_bytes)
        try:
            self._ensure_bucket()
            form = self._signing_client().presigned_post_policy(policy)
        except (S3Error, HTTPError) as exc:
            raise FileStoreUnavailableError("The file store is temporarily unavailable.") from exc
        scheme = "https" if self._settings.files_s3_secure else "http"
        fields = {"key": key, "Content-Type": content_type, **form}
        return SignedUpload(f"{scheme}://{self._public_endpoint}/{self._bucket}", fields, expires)

    def signed_download(self, key: str, *, file_name: str) -> str:
        try:
            self._ensure_bucket()
            return self._signing_client().presigned_get_object(
                self._bucket,
                key,
                expires=DOWNLOAD_LINK_LIFETIME,
                response_headers={"response-content-disposition": content_disposition(file_name)},
            )
        except (S3Error, HTTPError) as exc:
            raise FileStoreUnavailableError("The file store is temporarily unavailable.") from exc


class MemoryFileStore:
    """In-memory store for tests (and a reference for how a store must behave)."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.download_names: dict[str, str] = {}
        # Every signed upload handed out, so tests can see exactly what was allowed.
        self.signed_uploads: dict[str, tuple[str, int]] = {}

    def put(
        self, key: str, data: bytes, content_type: str, *, download_name: str | None = None
    ) -> None:
        self.objects[key] = (bytes(data), content_type)
        if download_name:
            self.download_names[key] = download_name

    def get(self, key: str) -> bytes:
        try:
            return self.objects[key][0]
        except KeyError:
            raise StoredFileMissingError("The file doesn't exist.") from None

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)
        self.download_names.pop(key, None)

    def stat(self, key: str) -> StoredObject:
        try:
            data, content_type = self.objects[key]
        except KeyError:
            raise StoredFileMissingError("The file doesn't exist.") from None
        return StoredObject(len(data), content_type)

    def signed_upload(self, key: str, *, content_type: str, max_bytes: int) -> SignedUpload:
        if max_bytes < 1:
            raise ValueError("max_bytes must be at least 1")
        self.signed_uploads[key] = (content_type, max_bytes)
        expires = datetime.now(UTC) + UPLOAD_LINK_LIFETIME
        fields = {"key": key, "Content-Type": content_type, "policy": "memory"}
        return SignedUpload("memory://files", fields, expires)

    def browser_upload(self, key: str, data: bytes) -> bool:
        """What the store does when a browser POSTs to a signed upload: refuse a key it did not
        sign, or a body larger than allowed. Tests use it instead of a real POST."""
        signed = self.signed_uploads.get(key)
        if signed is None or not 1 <= len(data) <= signed[1]:
            return False
        self.objects[key] = (bytes(data), signed[0])
        return True

    def signed_download(self, key: str, *, file_name: str) -> str:
        return f"memory://files/{quote(key)}?name={quote(file_name)}"


class UnconfiguredFileStore:
    """Used when no access key is set: storing files answers 503, everything else works."""

    def _fail(self) -> FileStoreUnavailableError:
        return FileStoreUnavailableError("File storage is not configured on this server.")

    def put(
        self, key: str, data: bytes, content_type: str, *, download_name: str | None = None
    ) -> None:
        raise self._fail()

    def get(self, key: str) -> bytes:
        raise self._fail()

    def delete(self, key: str) -> None:
        raise self._fail()

    def stat(self, key: str) -> StoredObject:
        raise self._fail()

    def signed_upload(self, key: str, *, content_type: str, max_bytes: int) -> SignedUpload:
        raise self._fail()

    def signed_download(self, key: str, *, file_name: str) -> str:
        raise self._fail()


def get_file_store(request: Request) -> FileStore:
    """FastAPI dependency: the store created at startup (tests put a MemoryFileStore there)."""
    store: FileStore = request.app.state.file_store
    return store


def build_file_store(settings: Settings) -> FileStore:
    if not settings.files_configured:
        return UnconfiguredFileStore()
    return S3FileStore(settings)

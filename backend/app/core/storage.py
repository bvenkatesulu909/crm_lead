"""File storage in an S3-compatible object store (ADR 0005; SeaweedFS locally).

``FileStore`` is a Protocol, so tests use ``MemoryFileStore`` and the running app uses
``S3FileStore``. Nothing else in the code talks to the store directly, which keeps swapping it
(MinIO, AWS S3, …) a settings change.

Every object key starts with ``tenant/{tenant_id}/`` (see ``object_key``). Keys are built only
from server-side IDs, never from file names or other client input. Authorization is NOT done
here: callers check permissions and record-level policies first, then read or write bytes.
"""

import io
import logging
import threading
import uuid
from typing import Protocol

import urllib3
from fastapi import Request
from minio import Minio
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


class FileStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes:
        """Raises ``StoredFileMissingError`` if there is no such object."""
        ...

    def delete(self, key: str) -> None:
        """Deleting a missing object is not an error (handlers may run twice)."""
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

    def _ensure_bucket(self) -> None:
        # Created on first use, so a fresh file store works without a manual setup step.
        if self._bucket_ready:
            return
        with self._lock:
            if not self._bucket_ready:
                if not self._client.bucket_exists(self._bucket):
                    self._client.make_bucket(self._bucket)
                self._bucket_ready = True

    def put(self, key: str, data: bytes, content_type: str) -> None:
        if len(data) > self._max_bytes:
            raise ValueError("file is larger than files_max_bytes")
        try:
            self._ensure_bucket()
            self._client.put_object(
                self._bucket, key, io.BytesIO(data), len(data), content_type=content_type
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


class MemoryFileStore:
    """In-memory store for tests (and a reference for how a store must behave)."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (bytes(data), content_type)

    def get(self, key: str) -> bytes:
        try:
            return self.objects[key][0]
        except KeyError:
            raise StoredFileMissingError("The file doesn't exist.") from None

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class UnconfiguredFileStore:
    """Used when no access key is set: storing files answers 503, everything else works."""

    def _fail(self) -> FileStoreUnavailableError:
        return FileStoreUnavailableError("File storage is not configured on this server.")

    def put(self, key: str, data: bytes, content_type: str) -> None:
        raise self._fail()

    def get(self, key: str) -> bytes:
        raise self._fail()

    def delete(self, key: str) -> None:
        raise self._fail()


def get_file_store(request: Request) -> FileStore:
    """FastAPI dependency: the store created at startup (tests put a MemoryFileStore there)."""
    store: FileStore = request.app.state.file_store
    return store


def build_file_store(settings: Settings) -> FileStore:
    if not settings.files_configured:
        return UnconfiguredFileStore()
    return S3FileStore(settings)

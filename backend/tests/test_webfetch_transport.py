"""The real transport of the fetcher (ADR 0019, step WC1) against a local TLS server.

The server has a self-signed certificate for ``registry.test``; the client is told to trust it.
The transport connects to a given address (here 127.0.0.1: the policy, tested elsewhere, is what
refuses such addresses) and checks the certificate against the host NAME."""

import datetime
import socket
import ssl
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.core.webfetch import PinnedRequest, TransportResponse, real_transport

NAME = "registry.test"


def make_certificate(directory: Path) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, NAME)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(NAME)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_file, key_file = directory / "cert.pem", directory / "key.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_file, key_file


class Server:
    """Answers one request per connection with whatever ``handler`` does."""

    def __init__(self, directory: Path) -> None:
        self.cert_file, key_file = make_certificate(directory)
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(self.cert_file, key_file)
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(5)
        self.port: int = self.listener.getsockname()[1]
        self.received: list[bytes] = []
        self.handler: Callable[[socket.socket], None] = lambda conn: None
        self.stop = False
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self) -> None:
        while not self.stop:
            try:
                raw, _ = self.listener.accept()
            except OSError:
                return
            try:
                with self.context.wrap_socket(raw, server_side=True) as conn:
                    data = b""
                    while b"\r\n\r\n" not in data:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    self.received.append(data)
                    self.handler(conn)
            except OSError:  # ssl.SSLError is an OSError: a refused certificate ends here
                pass

    def trusting(self) -> ssl.SSLContext:
        context = ssl.create_default_context()
        context.load_verify_locations(self.cert_file)
        return context


@pytest.fixture
def server(tmp_path: Path) -> Iterator[Server]:
    s = Server(tmp_path)
    yield s
    s.stop = True
    s.listener.close()


def request(server: Server, **options: object) -> PinnedRequest:
    values: dict[str, object] = {
        "ip": "127.0.0.1",
        "host": NAME,
        "target": "/search?q=A123",
        "headers": {"User-Agent": "crm-lead-webcheck/1.0", "Accept-Encoding": "identity"},
        "timeout": 5.0,
        "max_bytes": 10_000,
        "port": server.port,
    }
    values.update(options)
    return PinnedRequest(**values)  # type: ignore[arg-type]


def reply(status: str, body: bytes, extra: str = "") -> Callable[[socket.socket], None]:
    head = f"HTTP/1.1 {status}\r\nContent-Type: text/html\r\nContent-Length: {len(body)}\r\n{extra}"
    return lambda conn: conn.sendall(head.encode() + b"\r\n" + body)


def test_a_response_is_read_with_status_headers_and_body(server: Server) -> None:
    server.handler = reply("200 OK", b"<html>hello</html>", "X-Thing: Yes\r\n")
    response = real_transport(request(server), ssl_context=server.trusting())
    assert isinstance(response, TransportResponse)
    assert response.status == 200 and response.body == b"<html>hello</html>"
    assert response.truncated is False
    assert response.headers["content-type"] == "text/html" and response.headers["x-thing"] == "Yes"


def test_the_request_names_the_host_and_sends_only_our_headers(server: Server) -> None:
    server.handler = reply("200 OK", b"x")
    real_transport(request(server), ssl_context=server.trusting())
    sent = server.received[0].decode().lower()
    assert sent.startswith("get /search?q=a123 http/1.1")
    assert f"host: {NAME}" in sent and "user-agent: crm-lead-webcheck/1.0" in sent
    assert "cookie" not in sent and "authorization" not in sent


def test_a_body_over_the_limit_is_reported_as_cut(server: Server) -> None:
    server.handler = reply("200 OK", b"x" * 5000)
    response = real_transport(request(server, max_bytes=1000), ssl_context=server.trusting())
    assert response.truncated is True and len(response.body) <= 1000


def test_a_body_exactly_at_the_limit_is_not_cut(server: Server) -> None:
    server.handler = reply("200 OK", b"x" * 1000)
    response = real_transport(request(server, max_bytes=1000), ssl_context=server.trusting())
    assert response.truncated is False and len(response.body) == 1000


def test_a_redirect_is_returned_not_followed(server: Server) -> None:
    server.handler = reply("302 Found", b"", "Location: /elsewhere\r\n")
    response = real_transport(request(server), ssl_context=server.trusting())
    assert response.status == 302 and response.headers["location"] == "/elsewhere"
    assert len(server.received) == 1


def test_a_certificate_for_another_name_is_refused(server: Server) -> None:
    """We connect to an address but check the certificate against the NAME we meant."""
    server.handler = reply("200 OK", b"x")
    with pytest.raises(ssl.SSLError):
        real_transport(request(server, host="other.test"), ssl_context=server.trusting())


def test_an_untrusted_certificate_is_refused_by_default(server: Server) -> None:
    server.handler = reply("200 OK", b"x")
    with pytest.raises(ssl.SSLError):
        real_transport(request(server))


def test_a_server_that_never_answers_times_out(server: Server) -> None:
    server.handler = lambda conn: time.sleep(3)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        real_transport(request(server, timeout=0.5), ssl_context=server.trusting())
    assert time.monotonic() - started < 2.5


def test_a_server_that_drips_bytes_cannot_hold_the_total_time(server: Server) -> None:
    """The timeout is for the whole response, not for each read."""

    def drip(conn: socket.socket) -> None:
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 50\r\n\r\n")
        for _ in range(50):
            conn.sendall(b"x")
            time.sleep(0.1)

    server.handler = drip
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        real_transport(request(server, timeout=0.6), ssl_context=server.trusting())
    assert time.monotonic() - started < 2.5


def test_the_port_defaults_to_443() -> None:
    plain = PinnedRequest("93.184.216.34", NAME, "/", {}, 5.0, 1000)
    assert plain.port == 443

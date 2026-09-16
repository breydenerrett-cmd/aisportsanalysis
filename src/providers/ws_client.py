"""Minimal RFC 6455 WebSocket client over stdlib socket + ssl.

WHY THIS EXISTS
----------------
There is no `websockets` package available (stdlib only, per policy), and the
api-tennis.com Business-plan websocket feed (docs/API_TENNIS_TRIAL_RESULTS.md,
W-17 measurement) needed a client to test whether it changes check 9's
freshness verdict. This is that client: a handshake, masked client->server
frames, unmasked server->client frame parsing, ping/pong, and a clean close.
No TLS verification is disabled anywhere -- callers pass an `ssl.SSLContext`
they built themselves (this module never constructs one), so the caller
controls the trust store (see scripts/api_tennis_ws_probe.py, which sets
SSL_CERT_FILE before importing ssl-dependent code, never verify=False).

SCOPE
-----
Client-only, text/JSON frames only (this vendor's feed is JSON), no
extensions (permessage-deflate not implemented -- not offered by this
vendor), no fragmentation reassembly beyond the simple case tested here.
Good enough to probe one vendor feed; not a general-purpose library.
"""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import ssl
import struct
from dataclasses import dataclass
from typing import Callable, List, Optional
from urllib.parse import urlsplit

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OPCODE_CONTINUATION = 0x0
OPCODE_TEXT = 0x1
OPCODE_BINARY = 0x2
OPCODE_CLOSE = 0x8
OPCODE_PING = 0x9
OPCODE_PONG = 0xA


class WebSocketError(RuntimeError):
    """Raised for handshake or framing failures. Never carries a URL with a
    query string (callers must not pass one in; see build_request_path)."""


@dataclass
class Frame:
    opcode: int
    payload: bytes
    fin: bool = True


def _make_accept_key(sec_key: str) -> str:
    digest = hashlib.sha1((sec_key + _GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def build_handshake_request(host: str, path: str, sec_key: str,
                             extra_headers: Optional[dict] = None) -> bytes:
    """Builds the HTTP Upgrade request. `path` may include a query string
    (that's how this vendor takes the API key) but this function never logs
    or returns it anywhere except the bytes it hands back to the caller for
    sending directly over the socket."""
    headers = [
        f"GET {path} HTTP/1.1",
        f"Host: {host}",
        "Upgrade: websocket",
        "Connection: Upgrade",
        f"Sec-WebSocket-Key: {sec_key}",
        "Sec-WebSocket-Version: 13",
    ]
    for k, v in (extra_headers or {}).items():
        headers.append(f"{k}: {v}")
    headers.append("")
    headers.append("")
    return "\r\n".join(headers).encode("ascii")


def parse_handshake_response(response_bytes: bytes, sec_key: str) -> None:
    """Validates the server's HTTP 101 response and Sec-WebSocket-Accept.
    Raises WebSocketError on anything else."""
    text = response_bytes.decode("iso-8859-1", errors="replace")
    lines = text.split("\r\n")
    if not lines or "101" not in lines[0]:
        raise WebSocketError(f"handshake failed: status line {lines[0] if lines else '<empty>'!r}")
    headers = {}
    for line in lines[1:]:
        if not line or ":" not in line:
            continue
        k, _, v = line.partition(":")
        headers[k.strip().lower()] = v.strip()
    accept = headers.get("sec-websocket-accept")
    expected = _make_accept_key(sec_key)
    if accept != expected:
        raise WebSocketError("handshake failed: Sec-WebSocket-Accept mismatch")


def make_sec_key(random_bytes: bytes) -> str:
    """16 random bytes -> base64, per RFC 6455 4.1. Caller supplies the
    randomness (os.urandom in production, a fixed seed in tests)."""
    if len(random_bytes) != 16:
        raise ValueError("sec-websocket-key needs exactly 16 random bytes")
    return base64.b64encode(random_bytes).decode("ascii")


def encode_frame(opcode: int, payload: bytes, mask_bytes: bytes, fin: bool = True) -> bytes:
    """Encodes one client->server frame. Client frames MUST be masked
    (RFC 6455 5.1); mask_bytes is caller-supplied (4 random bytes in
    production, fixed in tests) so masking is deterministic and testable."""
    if len(mask_bytes) != 4:
        raise ValueError("mask_bytes must be exactly 4 bytes")
    first_byte = (0x80 if fin else 0x00) | (opcode & 0x0F)
    length = len(payload)
    out = bytearray([first_byte])
    if length < 126:
        out.append(0x80 | length)
    elif length < 65536:
        out.append(0x80 | 126)
        out += struct.pack(">H", length)
    else:
        out.append(0x80 | 127)
        out += struct.pack(">Q", length)
    out += mask_bytes
    masked = bytes(b ^ mask_bytes[i % 4] for i, b in enumerate(payload))
    out += masked
    return bytes(out)


class _ByteReader:
    """Reads exactly N bytes from a recv() callable, buffering excess."""

    def __init__(self, recv: Callable[[int], bytes]):
        self._recv = recv
        self._buf = b""

    def read_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self._recv(4096)
            if not chunk:
                raise WebSocketError("connection closed while reading frame")
            self._buf += chunk
        result, self._buf = self._buf[:n], self._buf[n:]
        return result

    def feed_leftover(self, data: bytes) -> None:
        self._buf = data + self._buf


def decode_frame(reader: _ByteReader) -> Frame:
    """Decodes exactly one server->client frame (unmasked, per RFC 6455 --
    a compliant server never masks). Raises WebSocketError if the server
    sends a masked frame (protocol violation)."""
    b1, b2 = reader.read_exact(2)
    fin = bool(b1 & 0x80)
    opcode = b1 & 0x0F
    masked = bool(b2 & 0x80)
    length = b2 & 0x7F
    if masked:
        raise WebSocketError("server sent a masked frame (protocol violation)")
    if length == 126:
        (length,) = struct.unpack(">H", reader.read_exact(2))
    elif length == 127:
        (length,) = struct.unpack(">Q", reader.read_exact(8))
    payload = reader.read_exact(length) if length else b""
    return Frame(opcode=opcode, payload=payload, fin=fin)


def decode_frames_from_buffer(data: bytes) -> List[Frame]:
    """Test/offline helper: decode every complete frame in a fixed byte
    buffer (no socket). Used by tests to exercise decode_frame without a
    real connection."""
    frames = []
    reader = _ByteReader(recv=lambda n: b"")
    reader.feed_leftover(data)
    while reader._buf:
        try:
            frames.append(decode_frame(reader))
        except WebSocketError:
            break
    return frames


class WebSocketClient:
    """A connected client-side websocket. Construct via `connect()`."""

    def __init__(self, sock: socket.socket, urandom: Callable[[int], bytes] = os.urandom):
        self._sock = sock
        self._reader = _ByteReader(recv=sock.recv)
        self._urandom = urandom
        self._closed = False

    def send_text(self, text: str) -> None:
        self._send(OPCODE_TEXT, text.encode("utf-8"))

    def send_ping(self, payload: bytes = b"") -> None:
        self._send(OPCODE_PING, payload)

    def send_pong(self, payload: bytes = b"") -> None:
        self._send(OPCODE_PONG, payload)

    def _send(self, opcode: int, payload: bytes) -> None:
        if self._closed:
            raise WebSocketError("cannot send on a closed connection")
        mask = self._urandom(4)
        self._sock.sendall(encode_frame(opcode, payload, mask))

    def recv_frame(self) -> Frame:
        return decode_frame(self._reader)

    def recv_message(self, on_ping: Optional[Callable[[bytes], None]] = None) -> Optional[str]:
        """Reads frames until one complete text message is assembled, or
        None if the connection was closed by the server. Auto-responds to
        pings with a pong (RFC 6455 5.5.2) unless on_ping is given, in which
        case the caller is responsible."""
        parts: List[bytes] = []
        opcode_in_progress: Optional[int] = None
        while True:
            frame = self.recv_frame()
            if frame.opcode == OPCODE_CLOSE:
                self._closed = True
                return None
            if frame.opcode == OPCODE_PING:
                if on_ping:
                    on_ping(frame.payload)
                else:
                    self.send_pong(frame.payload)
                continue
            if frame.opcode == OPCODE_PONG:
                continue
            if frame.opcode in (OPCODE_TEXT, OPCODE_BINARY):
                opcode_in_progress = frame.opcode
                parts = [frame.payload]
            elif frame.opcode == OPCODE_CONTINUATION:
                parts.append(frame.payload)
            if frame.fin:
                data = b"".join(parts)
                parts = []
                return data.decode("utf-8", errors="replace")

    def close(self, code: int = 1000, reason: bytes = b"") -> None:
        if self._closed:
            return
        try:
            payload = struct.pack(">H", code) + reason
            self._send(OPCODE_CLOSE, payload)
        except (WebSocketError, OSError):
            pass
        self._closed = True
        try:
            self._sock.close()
        except OSError:
            pass


def connect(url: str, *, ssl_context: ssl.SSLContext, timeout: float = 20.0,
            urandom: Callable[[int], bytes] = os.urandom,
            extra_headers: Optional[dict] = None) -> WebSocketClient:
    """Opens a TCP+TLS connection and performs the RFC 6455 handshake.

    `ssl_context` is REQUIRED and built by the caller -- this function never
    disables verification and never constructs its own context, so the
    caller's trust-store configuration (e.g. SSL_CERT_FILE) is always what
    gets used. `url` must be wss:// (this module does not support ws://).
    """
    parts = urlsplit(url)
    if parts.scheme != "wss":
        raise WebSocketError("only wss:// is supported")
    host = parts.hostname
    port = parts.port or 443
    path = parts.path or "/"
    if parts.query:
        path += f"?{parts.query}"

    raw_sock = socket.create_connection((host, port), timeout=timeout)
    tls_sock = ssl_context.wrap_socket(raw_sock, server_hostname=host)

    sec_key = make_sec_key(urandom(16))
    request = build_handshake_request(host, path, sec_key, extra_headers)
    tls_sock.sendall(request)

    reader = _ByteReader(recv=tls_sock.recv)
    header_bytes = b""
    while b"\r\n\r\n" not in header_bytes:
        chunk = tls_sock.recv(4096)
        if not chunk:
            raise WebSocketError("connection closed during handshake")
        header_bytes += chunk
    head, _, leftover = header_bytes.partition(b"\r\n\r\n")
    parse_handshake_response(head, sec_key)

    client = WebSocketClient(tls_sock, urandom=urandom)
    if leftover:
        client._reader.feed_leftover(leftover)
    return client

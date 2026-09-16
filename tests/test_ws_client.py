"""Unit tests for src/providers/ws_client.py -- RFC 6455 handshake and
framing, entirely offline (no network, no real clock). Frames are built and
parsed against fixed byte fixtures so the encode/decode logic is verified
independently of any live vendor."""

import struct
import unittest

from src.providers import ws_client as ws


class HandshakeTests(unittest.TestCase):
    def test_make_sec_key_is_deterministic_for_fixed_input(self):
        key = ws.make_sec_key(b"\x00" * 16)
        self.assertEqual(key, "AAAAAAAAAAAAAAAAAAAAAA==")

    def test_make_sec_key_rejects_wrong_length(self):
        with self.assertRaises(ValueError):
            ws.make_sec_key(b"\x00" * 10)

    def test_accept_key_matches_rfc6455_example(self):
        # RFC 6455 section 1.3 worked example.
        sec_key = "dGhlIHNhbXBsZSBub25jZQ=="
        expected_accept = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
        self.assertEqual(ws._make_accept_key(sec_key), expected_accept)

    def test_build_handshake_request_contains_required_headers(self):
        req = ws.build_handshake_request("example.com", "/live?APIkey=x", "abc123==")
        text = req.decode("ascii")
        self.assertIn("GET /live?APIkey=x HTTP/1.1", text)
        self.assertIn("Host: example.com", text)
        self.assertIn("Upgrade: websocket", text)
        self.assertIn("Sec-WebSocket-Key: abc123==", text)
        self.assertIn("Sec-WebSocket-Version: 13", text)
        self.assertTrue(text.endswith("\r\n\r\n"))

    def test_parse_handshake_response_accepts_valid_101(self):
        sec_key = "dGhlIHNhbXBsZSBub25jZQ=="
        accept = ws._make_accept_key(sec_key)
        response = (
            f"HTTP/1.1 101 Switching Protocols\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
        ).encode("ascii")
        ws.parse_handshake_response(response, sec_key)  # must not raise

    def test_parse_handshake_response_rejects_non_101(self):
        response = b"HTTP/1.1 401 Unauthorized\r\n\r\n"
        with self.assertRaises(ws.WebSocketError):
            ws.parse_handshake_response(response, "dGhlIHNhbXBsZSBub25jZQ==")

    def test_parse_handshake_response_rejects_wrong_accept(self):
        response = (
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Sec-WebSocket-Accept: not-the-right-value\r\n\r\n"
        )
        with self.assertRaises(ws.WebSocketError):
            ws.parse_handshake_response(response, "dGhlIHNhbXBsZSBub25jZQ==")


class FrameEncodingTests(unittest.TestCase):
    def test_encode_frame_masks_payload_and_sets_mask_bit(self):
        frame = ws.encode_frame(ws.OPCODE_TEXT, b"hi", mask_bytes=b"\x01\x02\x03\x04")
        # first byte: FIN=1, opcode=0x1 -> 0x81
        self.assertEqual(frame[0], 0x81)
        # second byte: MASK bit set + length 2 -> 0x82
        self.assertEqual(frame[1], 0x82)
        mask = frame[2:6]
        self.assertEqual(mask, b"\x01\x02\x03\x04")
        masked_payload = frame[6:]
        unmasked = bytes(b ^ mask[i % 4] for i, b in enumerate(masked_payload))
        self.assertEqual(unmasked, b"hi")

    def test_encode_frame_rejects_bad_mask_length(self):
        with self.assertRaises(ValueError):
            ws.encode_frame(ws.OPCODE_TEXT, b"x", mask_bytes=b"\x01\x02")

    def test_encode_frame_extended_length_16bit(self):
        payload = b"a" * 200
        frame = ws.encode_frame(ws.OPCODE_BINARY, payload, mask_bytes=b"\x00\x00\x00\x00")
        self.assertEqual(frame[1] & 0x7F, 126)
        (length,) = struct.unpack(">H", frame[2:4])
        self.assertEqual(length, 200)


def _server_frame(opcode: int, payload: bytes, fin: bool = True) -> bytes:
    """Builds an UNMASKED server->client frame (servers never mask)."""
    first_byte = (0x80 if fin else 0x00) | (opcode & 0x0F)
    length = len(payload)
    out = bytearray([first_byte])
    if length < 126:
        out.append(length)
    elif length < 65536:
        out.append(126)
        out += struct.pack(">H", length)
    else:
        out.append(127)
        out += struct.pack(">Q", length)
    out += payload
    return bytes(out)


class FrameDecodingTests(unittest.TestCase):
    def test_decode_single_text_frame(self):
        data = _server_frame(ws.OPCODE_TEXT, b'{"a":1}')
        frames = ws.decode_frames_from_buffer(data)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].opcode, ws.OPCODE_TEXT)
        self.assertEqual(frames[0].payload, b'{"a":1}')
        self.assertTrue(frames[0].fin)

    def test_decode_rejects_masked_server_frame(self):
        # A masked frame from the "server" is a protocol violation.
        masked = ws.encode_frame(ws.OPCODE_TEXT, b"x", mask_bytes=b"\x01\x02\x03\x04")
        with self.assertRaises(ws.WebSocketError):
            reader = ws._ByteReader(recv=lambda n: b"")
            reader.feed_leftover(masked)
            ws.decode_frame(reader)

    def test_decode_extended_length_16bit_payload(self):
        payload = b"y" * 300
        data = _server_frame(ws.OPCODE_BINARY, payload)
        frames = ws.decode_frames_from_buffer(data)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].payload, payload)

    def test_decode_multiple_frames_in_one_buffer(self):
        data = _server_frame(ws.OPCODE_TEXT, b"one") + _server_frame(ws.OPCODE_TEXT, b"two")
        frames = ws.decode_frames_from_buffer(data)
        self.assertEqual([f.payload for f in frames], [b"one", b"two"])


class _FakeSocket:
    """Fake socket for WebSocketClient tests: recv() serves from a queue of
    byte chunks, sendall() records what was sent. No real network."""

    def __init__(self, recv_chunks):
        self._chunks = list(recv_chunks)
        self.sent = []

    def recv(self, n):
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    def sendall(self, data):
        self.sent.append(data)

    def close(self):
        pass


class WebSocketClientTests(unittest.TestCase):
    def test_recv_message_returns_text_payload(self):
        data = _server_frame(ws.OPCODE_TEXT, b'{"hello":"world"}')
        sock = _FakeSocket([data])
        client = ws.WebSocketClient(sock, urandom=lambda n: b"\x00" * n)
        message = client.recv_message()
        self.assertEqual(message, '{"hello":"world"}')

    def test_recv_message_returns_none_on_close_frame(self):
        close_frame = _server_frame(ws.OPCODE_CLOSE, struct.pack(">H", 1000))
        sock = _FakeSocket([close_frame])
        client = ws.WebSocketClient(sock, urandom=lambda n: b"\x00" * n)
        self.assertIsNone(client.recv_message())

    def test_recv_message_auto_pongs_a_ping_then_returns_next_text(self):
        ping = _server_frame(ws.OPCODE_PING, b"ping-payload")
        text = _server_frame(ws.OPCODE_TEXT, b'{"x":1}')
        sock = _FakeSocket([ping + text])
        client = ws.WebSocketClient(sock, urandom=lambda n: b"\x00" * n)
        message = client.recv_message()
        self.assertEqual(message, '{"x":1}')
        # exactly one frame was sent back (the auto-pong)
        self.assertEqual(len(sock.sent), 1)
        sent = sock.sent[0]
        self.assertEqual(sent[0] & 0x0F, ws.OPCODE_PONG)

    def test_send_text_masks_and_sends(self):
        sock = _FakeSocket([])
        client = ws.WebSocketClient(sock, urandom=lambda n: b"\x01\x02\x03\x04")
        client.send_text("hi")
        self.assertEqual(len(sock.sent), 1)
        sent = sock.sent[0]
        self.assertEqual(sent[0], 0x81)  # FIN + text opcode
        self.assertTrue(sent[1] & 0x80)  # mask bit set

    def test_close_is_idempotent(self):
        sock = _FakeSocket([])
        client = ws.WebSocketClient(sock, urandom=lambda n: b"\x00" * n)
        client.close()
        client.close()  # must not raise
        self.assertEqual(len(sock.sent), 1)


if __name__ == "__main__":
    unittest.main()

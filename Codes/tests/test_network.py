"""Integration tests for A's raw TCP and JSON-lines server layer."""

import json
import socket
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol import JsonLineBuffer, encode_message  # noqa: E402
from server import Server  # noqa: E402


class NetworkTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = Server("127.0.0.1", 0, Path(__file__).resolve().parents[1] / "questions.json")
        cls.server_thread = threading.Thread(target=cls.server.start, daemon=True)
        cls.server_thread.start()
        deadline = time.monotonic() + 2
        while cls.server.bound_address is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if cls.server.bound_address is None:
            raise AssertionError("server did not start")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server_thread.join(2)

    def setUp(self) -> None:
        if self.server.bound_address is None:
            raise AssertionError("server did not bind")
        self.connection = socket.create_connection(self.server.bound_address, timeout=2)
        self.buffer = JsonLineBuffer()
        self.pending_messages: list[dict] = []

    def tearDown(self) -> None:
        self.connection.close()

    def send_raw(self, payload: bytes) -> None:
        self.connection.sendall(payload)

    def send_json(self, message: dict) -> None:
        self.send_raw(encode_message(message))

    def receive_one(self) -> dict:
        while True:
            if self.pending_messages:
                return self.pending_messages.pop(0)
            data = self.connection.recv(4096)
            if not data:
                raise AssertionError("server closed the connection")
            messages = self.buffer.feed(data)
            if messages:
                self.pending_messages.extend(messages)

    def test_hello_and_ping(self) -> None:
        self.send_json({
            "type": "hello",
            "request_id": "hello-1",
            "user_id": "alice",
            "name": "Alice",
        })
        self.assertEqual(self.receive_one()["data"]["user_id"], "alice")

        self.send_json({"type": "ping", "request_id": "ping-1"})
        reply = self.receive_one()
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["data"]["message"], "pong")

    def test_fragmented_and_coalesced_json_lines(self) -> None:
        first = encode_message({"type": "ping", "request_id": "one"})
        second = encode_message({"type": "ping", "request_id": "two"})
        split_at = max(1, len(first) // 2)
        self.send_raw(first[:split_at])
        self.send_raw(first[split_at:] + second)

        replies = [self.receive_one(), self.receive_one()]
        self.assertEqual({reply["request_id"] for reply in replies}, {"one", "two"})

    def test_duplicate_active_user_id_is_rejected(self) -> None:
        self.send_json({
            "type": "hello",
            "request_id": "first",
            "user_id": "same-id",
            "name": "First",
        })
        self.assertTrue(self.receive_one()["ok"])

        second = socket.create_connection(self.server.bound_address, timeout=2)
        try:
            second.sendall(encode_message({
                "type": "hello",
                "request_id": "second",
                "user_id": "same-id",
                "name": "Second",
            }))
            buffer = JsonLineBuffer()
            reply = buffer.feed(second.recv(4096))[0]
            self.assertFalse(reply["ok"])
            self.assertEqual(reply["error"]["code"], "DUPLICATE_USER_ID")
        finally:
            second.close()

    def test_bad_json_and_unknown_command_return_errors(self) -> None:
        self.send_raw(b"not-json\n")
        self.assertFalse(self.receive_one()["ok"])

        old_connection = self.connection
        self.connection = socket.create_connection(self.server.bound_address, timeout=2)
        old_connection.close()
        self.buffer = JsonLineBuffer()
        self.send_json({"type": "not-a-command", "request_id": "unknown"})
        reply = self.receive_one()
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["error"]["code"], "UNKNOWN_COMMAND")

    def test_two_clients_have_independent_connections(self) -> None:
        other = socket.create_connection(self.server.bound_address, timeout=2)
        try:
            self.send_json({"type": "ping", "request_id": "client-one"})
            other.sendall(encode_message({"type": "ping", "request_id": "client-two"}))
            self.assertEqual(self.receive_one()["request_id"], "client-one")
            other_buffer = JsonLineBuffer()
            other_reply = other_buffer.feed(other.recv(4096))[0]
            self.assertEqual(other_reply["request_id"], "client-two")
        finally:
            other.close()


if __name__ == "__main__":
    unittest.main()

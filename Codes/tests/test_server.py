"""服务端输出边界测试。"""

import contextlib
import io
import json
import socket
import sys
import threading
import time
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import ClientSession


class FakeConnection:
    def __init__(self):
        self.sent = []

    def sendall(self, data):
        self.sent.append(data)


class SendResponseTest(unittest.TestCase):
    def test_encode_failure_is_logged_and_not_sent(self):
        connection = FakeConnection()
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            sent = ClientSession(connection, ("127.0.0.1", 5000)).send({"bad": object()})

        self.assertFalse(sent)
        self.assertEqual(connection.sent, [])
        self.assertIn("无法编码", output.getvalue())

    def test_valid_response_is_encoded_and_sent(self):
        connection = FakeConnection()

        sent = ClientSession(connection, ("127.0.0.1", 5000)).send(
            {"type": "response", "ok": True}
        )

        self.assertTrue(sent)
        self.assertEqual(connection.sent, [b'{"type":"response","ok":true}\n'])

    def test_closed_socket_returns_false_instead_of_raising(self):
        connection, peer = socket.socketpair()
        session = ClientSession(connection, ("127.0.0.1", 5000))
        connection.close()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                sent = session.send({"type": "response", "ok": True})
            self.assertFalse(sent)
        finally:
            peer.close()

    def test_concurrent_writers_keep_each_json_frame_intact(self):
        # 强制把每次发送分成两段，给另一个线程抢写的机会。
        class SplitWriteConnection:
            def __init__(self, connection):
                self.connection = connection

            def sendall(self, payload):
                middle = len(payload) // 2
                self.connection.sendall(payload[:middle])
                time.sleep(0.002)
                self.connection.sendall(payload[middle:])

        connection, peer = socket.socketpair()
        connection.settimeout(5)
        peer.settimeout(5)
        session = ClientSession(SplitWriteConnection(connection), ("127.0.0.1", 5000))
        start = threading.Barrier(3)
        failures = []

        def write_messages(text, is_event):
            try:
                start.wait(timeout=5)
                for _ in range(8):
                    if is_event:
                        sent = session.send_event("demo_notice", {"text": text})
                    else:
                        sent = session.send({"type": "response", "text": text})
                    if not sent:
                        failures.append("send failed")
                        return
            except Exception as exc:
                failures.append(repr(exc))

        workers = [
            threading.Thread(target=write_messages, args=(text, is_event), daemon=True)
            for text, is_event in (("A" * 4096, False), ("B" * 4096, True))
        ]
        try:
            for worker in workers:
                worker.start()
            start.wait(timeout=5)
            received = bytearray()
            while received.count(b"\n") < 16:
                chunk = peer.recv(8192)
                self.assertTrue(chunk, "connection closed before all responses arrived")
                received.extend(chunk)
            for worker in workers:
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive(), "sender did not finish")
            self.assertEqual(failures, [])
            try:
                messages = [json.loads(line) for line in received.splitlines()]
            except json.JSONDecodeError as exc:
                self.fail(f"并发发送破坏了 JSON 消息边界：{exc}")
            self.assertCountEqual(messages, [
                {"type": "response", "text": "A" * 4096},
            ] * 8 + [
                {"type": "event", "event": "demo_notice", "data": {"text": "B" * 4096}},
            ] * 8)
        finally:
            connection.close()
            peer.close()
            for worker in workers:
                worker.join(timeout=5)


if __name__ == "__main__":
    unittest.main()

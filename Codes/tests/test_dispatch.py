"""请求交接、定向事件、广播及临时客户端分类测试。"""

import contextlib
import io
import json
from pathlib import Path
import socket
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol import decode_message, encode_message, extract_messages
from server import ClientSession, Server
import server_temp_test


def read_messages(peer, count):
    buffer = bytearray()
    messages = []
    while len(messages) < count:
        chunk = peer.recv(8192)
        if not chunk:
            raise AssertionError("连接在全部消息到达前关闭")
        buffer.extend(chunk)
        messages.extend(decode_message(frame) for frame in extract_messages(buffer))
    return messages


class DispatchTest(unittest.TestCase):
    def test_malformed_frame_then_custom_handler_event_and_response(self):
        connection, peer = socket.socketpair()
        connection.settimeout(3)
        peer.settimeout(3)
        self.addCleanup(peer.close)
        self.addCleanup(connection.close)
        session = ClientSession(connection, ("local", 1))
        calls = []

        def handle_request(current_session, message):
            calls.append((current_session, message))
            current_session.send_event("demo_notice", {"text": "服务器通知"})
            return {
                "type": "response", "request_id": message["request_id"],
                "ok": True, "data": {"handled": True},
            }

        server = Server("127.0.0.1", 0, request_handler=handle_request)
        server.sessions.add(session)
        worker = threading.Thread(target=server.handle_client, args=(session,), daemon=True)
        worker.start()
        request = {"type": "demo", "request_id": 7}
        try:
            peer.sendall(b"{bad json}\n" + encode_message(request))
            messages = read_messages(peer, 3)
            self.assertEqual(messages[0]["error"]["code"], "MALFORMED_MESSAGE")
            self.assertEqual(messages[1], {
                "type": "event", "event": "demo_notice", "data": {"text": "服务器通知"},
            })
            self.assertEqual(messages[2], {
                "type": "response", "request_id": 7, "ok": True, "data": {"handled": True},
            })
            self.assertEqual(calls, [(session, request)])
        finally:
            peer.close()
            worker.join(timeout=4)
        self.assertFalse(worker.is_alive(), "客户端线程没有退出")
        self.assertNotIn(session, server.sessions)

    def test_broadcast_only_targets_given_sessions_and_reports_failed_send(self):
        pairs = [socket.socketpair() for _ in range(4)]
        for connection, peer in pairs:
            connection.settimeout(3)
            peer.settimeout(3)
            self.addCleanup(connection.close)
            self.addCleanup(peer.close)
        sessions = [ClientSession(connection, ("local", index))
                    for index, (connection, _) in enumerate(pairs)]
        pairs[0][0].close()  # 第一位发送失败，后面两位仍应收到；第四位不在目标房间。
        server = Server("127.0.0.1", 0)
        server.sessions.update(sessions)

        with contextlib.redirect_stdout(io.StringIO()):
            failed = server.broadcast_event(sessions[:3], "room_update", {"room_id": "R1"})

        self.assertEqual(failed, [sessions[0]])
        for _, peer in pairs[1:3]:
            self.assertEqual(read_messages(peer, 1), [{
                "type": "event", "event": "room_update", "data": {"room_id": "R1"},
            }])
        pairs[3][1].setblocking(False)
        with self.assertRaises(BlockingIOError):
            pairs[3][1].recv(1)

    def test_temporary_client_does_not_count_event_as_reply(self):
        connection, peer = socket.socketpair()
        connection.settimeout(3)
        peer.settimeout(3)
        self.addCleanup(connection.close)
        self.addCleanup(peer.close)
        messages = [
            {"type": "event", "event": "demo_notice", "data": {}},
            {"type": "response", "request_id": 1, "ok": True, "data": {}},
            {"type": "response", "request_id": 2, "ok": False, "error": {"code": "UNKNOWN_COMMAND"}},
        ]
        peer.sendall(b"".join(encode_message(message) for message in messages))
        # 如果错误地把 event 算作回复，客户端会提前返回，下面这个错误响应不会输出。
        output = io.StringIO()
        class BytewiseReader:
            def recv(self, size):
                return connection.recv(1)

        with contextlib.redirect_stdout(output):
            server_temp_test.receive_replies(BytewiseReader(), expected_replies=2)
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("收到事件："))
        self.assertTrue(lines[1].startswith("收到响应："))
        self.assertTrue(lines[2].startswith("收到失败："))
        self.assertEqual(json.loads(lines[2].split("：", 1)[1]), messages[2])


if __name__ == "__main__":
    unittest.main()

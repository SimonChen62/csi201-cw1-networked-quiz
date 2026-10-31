"""网络失败关闭、编码失败隔离与断线回调测试。"""

from pathlib import Path
import socket
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol import decode_message, encode_message
from server import ClientSession, Server


class DisconnectTest(unittest.TestCase):
    def make_session(self):
        connection, peer = socket.socketpair()
        connection.settimeout(3)
        peer.settimeout(3)
        self.addCleanup(connection.close)
        self.addCleanup(peer.close)
        return ClientSession(connection, ("local", 1)), peer

    def start_worker(self, server, session):
        server.sessions.add(session)
        worker = threading.Thread(target=server.handle_client, args=(session,), daemon=True)
        worker.start()
        def cleanup():
            session.close()
            worker.join(timeout=4)
        self.addCleanup(cleanup)
        return worker

    def test_encoding_failure_does_not_close_healthy_connection(self):
        session, peer = self.make_session()
        self.assertFalse(session.send_event("demo", {"bad": object()}))
        self.assertFalse(session.closed.is_set())
        self.assertTrue(session.send_event("demo", {"text": "正常"}))
        with peer.makefile("rb") as reader:
            self.assertEqual(decode_message(reader.readline()), {
                "type": "event", "event": "demo", "data": {"text": "正常"},
            })

    def test_repeated_close_unblocks_reader_and_notifies_once_outside_lock(self):
        session, peer = self.make_session()
        notices = []
        lock_available = []

        def on_disconnect(current):
            acquired = server.sessions_lock.acquire(blocking=False)
            lock_available.append(acquired)
            if acquired:
                server.sessions_lock.release()
            notices.append(current)

        server = Server("127.0.0.1", 0, on_disconnect=on_disconnect)
        worker = self.start_worker(server, session)
        closers = [threading.Thread(target=session.close) for _ in range(2)]
        for closer in closers:
            closer.start()
        for closer in closers:
            closer.join(timeout=3)
            self.assertFalse(closer.is_alive())
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(peer.recv(1), b"")
        self.assertNotIn(session, server.sessions)
        self.assertEqual(notices, [session])
        self.assertEqual(lock_available, [True])

    def test_broadcast_network_failure_wakes_worker_and_notifies_business(self):
        session, peer = self.make_session()
        # 只关闭发送方向：后续发送必然失败，接收方向仍可能阻塞。
        session.connection.shutdown(socket.SHUT_WR)
        notices = []
        server = Server("127.0.0.1", 0, on_disconnect=notices.append)
        worker = self.start_worker(server, session)

        failed = server.broadcast_event([session], "demo", {})

        worker.join(timeout=1)
        self.assertEqual(failed, [session])
        self.assertTrue(session.closed.is_set())
        self.assertFalse(worker.is_alive())
        self.assertNotIn(session, server.sessions)
        self.assertEqual(notices, [session])

    def test_unencodable_reply_returns_internal_error_and_connection_can_continue(self):
        session, peer = self.make_session()

        def handler(current, request):
            if request["type"] == "broken":
                return {"type": "response", "data": object()}
            return Server.handle_request(current, request)

        server = Server("127.0.0.1", 0, request_handler=handler)
        self.start_worker(server, session)
        peer.sendall(encode_message({"type": "broken", "request_id": 1}) +
                     encode_message({"type": "echo", "request_id": 2, "text": "still here"}))
        with peer.makefile("rb") as reader:
            error = decode_message(reader.readline())
            response = decode_message(reader.readline())
        self.assertEqual(error["error"]["code"], "INTERNAL_ERROR")
        self.assertEqual(response["request_id"], 2)
        self.assertEqual(response["data"], {"text": "still here"})
        self.assertFalse(session.closed.is_set())

    def test_broadcast_encoding_failure_keeps_sessions_registered(self):
        session, peer = self.make_session()
        server = Server("127.0.0.1", 0)
        server.sessions.add(session)
        self.assertEqual(server.broadcast_event([session], "demo", {"bad": object()}), [session])
        self.assertFalse(session.closed.is_set())
        self.assertIn(session, server.sessions)

    def test_callback_error_does_not_break_other_client(self):
        first, first_peer = self.make_session()
        second, second_peer = self.make_session()

        def broken_callback(session):
            raise RuntimeError("模拟业务清理失败")

        server = Server("127.0.0.1", 0, on_disconnect=broken_callback)
        first_worker = self.start_worker(server, first)
        self.start_worker(server, second)
        first_peer.close()
        first_worker.join(timeout=4)
        self.assertFalse(first_worker.is_alive())
        self.assertNotIn(first, server.sessions)
        second_peer.sendall(encode_message({"type": "echo", "request_id": 9, "text": "alive"}))
        with second_peer.makefile("rb") as reader:
            response = decode_message(reader.readline())
        self.assertEqual(response["data"], {"text": "alive"})

    def test_stop_request_then_shutdown_still_closes_connections(self):
        session, peer = self.make_session()
        notices = []
        server = Server("127.0.0.1", 0, on_disconnect=notices.append)
        worker = self.start_worker(server, session)
        server.request_shutdown()
        server.shutdown()
        server.shutdown()
        worker.join(timeout=4)
        self.assertFalse(worker.is_alive())
        self.assertEqual(peer.recv(1), b"")
        self.assertEqual(notices, [session])

    def test_shutdown_waits_until_disconnect_callback_finishes(self):
        session, peer = self.make_session()
        callback_started = threading.Event()
        release_callback = threading.Event()

        def slow_callback(current):
            callback_started.set()
            release_callback.wait(timeout=3)

        server = Server("127.0.0.1", 0, on_disconnect=slow_callback)
        worker = server.start_client(session)
        shutdown_thread = threading.Thread(target=server.shutdown)
        try:
            shutdown_thread.start()
            self.assertTrue(callback_started.wait(timeout=2), "断线回调没有开始")
            self.assertTrue(shutdown_thread.is_alive(), "shutdown 没有等待断线回调完成")
            release_callback.set()
            shutdown_thread.join(timeout=3)
            self.assertFalse(shutdown_thread.is_alive(), "shutdown 未能结束")
            worker.join(timeout=1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(server.client_threads, set())
        finally:
            release_callback.set()
            if shutdown_thread.is_alive():
                shutdown_thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()

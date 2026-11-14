"""服务端启动参数和题库先校验后监听测试。"""

import contextlib
import io
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server


class FakeServer:
    def __init__(self, host, port, question_bank=None, **callbacks):
        self.host = host
        self.port = port
        self.question_bank = question_bank
        self.callbacks = callbacks

    def serve_forever(self):
        pass

    def shutdown(self):
        pass

    def request_shutdown(self, *_):
        pass


class StartupTest(unittest.TestCase):
    def test_question_bank_is_loaded_before_server_starts_listening(self):
        bank = {"quizzes": ["already validated"]}
        order = []
        servers = []

        def load_bank(path):
            order.append(("load", path))
            return bank

        class RecordingServer(FakeServer):
            def __init__(self, host, port, question_bank=None, **callbacks):
                super().__init__(host, port, question_bank, **callbacks)
                servers.append(self)

            def serve_forever(self):
                order.append(("listen", self.question_bank))

        with mock.patch.object(server, "Server", RecordingServer), \
             mock.patch.object(server.signal, "signal"):
            result = server.main(
                ["--host", "0.0.0.0", "--port", "6123", "--questions", "questions.json"],
                question_loader=load_bank,
            )

        self.assertEqual(result, 0)
        self.assertEqual(order, [("load", "questions.json"), ("listen", bank)])
        self.assertEqual(servers[0].host, "0.0.0.0")
        self.assertEqual(servers[0].port, 6123)
        self.assertTrue(callable(servers[0].callbacks["request_handler"]))
        self.assertTrue(callable(servers[0].callbacks["on_disconnect"]))

    def test_invalid_question_bank_prevents_server_from_starting(self):
        server_factory = mock.Mock()
        output = io.StringIO()

        def reject_bank(path):
            raise ValueError("questions[0] is invalid")

        with mock.patch.object(server, "Server", server_factory), \
             contextlib.redirect_stdout(output):
            result = server.main(
                ["--host", "127.0.0.1", "--port", "6123", "--questions", "bad.json"],
                question_loader=reject_bank,
            )

        self.assertEqual(result, 1)
        server_factory.assert_not_called()
        self.assertIn("questions[0] is invalid", output.getvalue())

    def test_lab_mode_keeps_echo_server_available(self):
        with mock.patch.object(server, "Server", FakeServer), \
             mock.patch.object(server.signal, "signal"):
            result = server.main([
                "--host", "127.0.0.1", "--port", "6123", "--lab-mode",
            ])

        self.assertEqual(result, 0)

    def test_startup_requires_questions_or_explicit_lab_mode(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output), self.assertRaises(SystemExit) as raised:
            server.main([
                "--host", "127.0.0.1", "--port", "6123",
            ])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("one of the arguments --questions --lab-mode is required", output.getvalue())

    def test_host_and_port_are_required(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output), self.assertRaises(SystemExit) as raised:
            server.main(["--questions", "questions.json"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("the following arguments are required: --host, --port", output.getvalue())

    def test_lab_mode_cannot_be_combined_with_questions(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output), self.assertRaises(SystemExit) as raised:
            server.main([
                "--host", "127.0.0.1", "--port", "6123",
                "--lab-mode", "--questions", "questions.json",
            ])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("not allowed with argument", output.getvalue())

    def test_formal_mode_prints_ready_marker_after_binding(self):
        running_server = server.Server("127.0.0.1", 0, question_bank={"quizzes": []})
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            listener_thread = threading.Thread(target=running_server.serve_forever)
            listener_thread.start()
            deadline = time.monotonic() + 2
            while not output.getvalue() and time.monotonic() < deadline:
                time.sleep(0.01)
            running_server.request_shutdown()
            listener_thread.join(timeout=2)
            running_server.shutdown()

        self.assertFalse(listener_thread.is_alive())
        self.assertRegex(output.getvalue(), r"SERVER_READY 127\.0\.0\.1 \d+")


if __name__ == "__main__":
    unittest.main()

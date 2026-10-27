"""服务端输出边界测试。"""

import contextlib
import io
import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import send_response


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
            sent = send_response(connection, {"bad": object()})

        self.assertFalse(sent)
        self.assertEqual(connection.sent, [])
        self.assertIn("无法编码", output.getvalue())

    def test_valid_response_is_encoded_and_sent(self):
        connection = FakeConnection()

        sent = send_response(connection, {"type": "response", "ok": True})

        self.assertTrue(sent)
        self.assertEqual(connection.sent, [b'{"type":"response","ok":true}\n'])


if __name__ == "__main__":
    unittest.main()

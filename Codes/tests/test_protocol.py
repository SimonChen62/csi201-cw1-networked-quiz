"""阶段 4：JSON 换行协议的编解码和边界检查。"""

import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol import (
    MAX_MESSAGE_BYTES,
    MessageTooLarge,
    ProtocolError,
    decode_message,
    encode_message,
    extract_messages,
)


class ProtocolTest(unittest.TestCase):
    def test_json_round_trip_preserves_unicode_and_adds_newline(self):
        message = {"type": "echo", "request_id": 7, "text": "你好"}

        encoded = encode_message(message)

        self.assertEqual(encoded, '{"type":"echo","request_id":7,"text":"你好"}\n'.encode("utf-8"))
        self.assertEqual(decode_message(encoded[:-1]), message)

    def test_extractor_keeps_partial_line_and_reads_multiple_lines(self):
        buffer = bytearray(b'{"type":"echo"}\n{"type":')

        messages = extract_messages(buffer)

        self.assertEqual(messages, [b'{"type":"echo"}'])
        self.assertEqual(buffer, b'{"type":')

        buffer.extend(b'"echo"}\n')
        messages = extract_messages(buffer)

        self.assertEqual(messages, [b'{"type":"echo"}'])
        self.assertEqual(buffer, b"")

    def test_rejects_invalid_json_and_non_object_values(self):
        for payload in (b"{bad json}", b"[]"):
            with self.subTest(payload=payload), self.assertRaises(ProtocolError):
                decode_message(payload)

    def test_rejects_frame_larger_than_limit(self):
        with self.assertRaises(MessageTooLarge):
            extract_messages(bytearray(b"x" * (MAX_MESSAGE_BYTES + 1)))


if __name__ == "__main__":
    unittest.main()

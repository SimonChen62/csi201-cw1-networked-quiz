"""Shared JSON-lines framing for the client and server."""

import json


MAX_MESSAGE_BYTES = 64 * 1024


def encode_message(message: dict) -> bytes:
    """Encode one application message, including its TCP frame delimiter."""
    payload = json.dumps(message, ensure_ascii=True, separators=(",", ":"))
    encoded = (payload + "\n").encode("utf-8")
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise ValueError("message is too large")
    return encoded


class JsonLineBuffer:
    """Turn arbitrary recv() chunks into complete JSON messages."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[dict]:
        self._buffer.extend(data)
        if len(self._buffer) > MAX_MESSAGE_BYTES * 2:
            raise ValueError("receive buffer is too large")

        messages: list[dict] = []
        while b"\n" in self._buffer:
            raw_line, _, remainder = self._buffer.partition(b"\n")
            self._buffer = bytearray(remainder)
            if not raw_line.strip():
                continue
            if len(raw_line) > MAX_MESSAGE_BYTES:
                raise ValueError("message is too large")
            value = json.loads(raw_line.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("message must be a JSON object")
            messages.append(value)
        return messages

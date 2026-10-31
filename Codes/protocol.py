r"""
Author: SimonChen62 430395359@qq.com
Date: 2026-10-27 01:28:20
LastEditors: SimonChen62 430395359@qq.com
LastEditTime: 2026-10-27 22:17:14
FilePath: \Codes\protocol.py
Description: JSON message encoding, decoding and newline framing.
"""


import json


MAX_MESSAGE_BYTES = 64 * 1024


class ProtocolError(ValueError):
    """Invalid protocol message, including UTF-8 or JSON errors."""


# MessageTooLarge inherits from ProtocolError.
class MessageTooLarge(ProtocolError):
    """Message size exceeds the byte limit."""


def extract_messages(buffer: bytearray) -> list[bytes]:
    r"""Split complete frames at b'\n', keeping each frame within 64 KiB.

    Args:
        buffer: Receive buffer, modified in place; an incomplete tail is kept.

    Returns:
        Complete frames without their newline delimiters.
    """
    messages = []
    while True:
        # Find the frame delimiter.
        newline = buffer.find(b"\n")
        if newline == -1:
            if len(buffer) > MAX_MESSAGE_BYTES:
                raise MessageTooLarge("message exceeds 64 KB")
            return messages
        if newline > MAX_MESSAGE_BYTES:
            raise MessageTooLarge("message exceeds 64 KB")
        messages.append(bytes(buffer[:newline]))
        del buffer[:newline + 1]


def encode_message(message: dict[str, object]) -> bytes:
    """Encode a message dictionary as UTF-8 JSON followed by a newline.

    Args:
        message: The message dictionary to encode.

    Returns:
        The encoded frame as bytes.
    """
    try:
        # Convert the dictionary to JSON, then encode it as UTF-8.
        payload = json.dumps(
            message,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ProtocolError(f"cannot encode message: {exc}") from exc
    if len(payload) > MAX_MESSAGE_BYTES:
        raise MessageTooLarge("message exceeds 64 KB")
    return payload + b"\n"


def decode_message(payload: bytes) -> dict[str, object]:
    """Decode a UTF-8 JSON frame into a dictionary.

    Args:
        payload: The frame bytes to decode.

    Returns:
        The decoded message dictionary.
    """
    if len(payload) > MAX_MESSAGE_BYTES:
        raise MessageTooLarge("message exceeds 64 KB")
    try:
        message = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"invalid JSON message: {exc}") from exc
    if not isinstance(message, dict):
        raise ProtocolError("message must be a JSON object")
    return message

"""Temporary test client for A's experiments; not the official D/E client."""

import argparse
import json
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol import decode_message, encode_message, extract_messages


def receive_replies(connection, expected_replies):
    buffer = bytearray()
    replies = 0
    while replies < expected_replies:
        chunk = connection.recv(1024)
        if not chunk:
            raise RuntimeError("server closed the connection before replying to every message")
        buffer.extend(chunk)
        for frame in extract_messages(buffer):
            message = decode_message(frame)
            text = json.dumps(message, ensure_ascii=False)
            if message.get("type") == "event":
                print(f"Received event: {text}")
            elif message.get("type") == "response":
                label = "Received response" if message.get("ok") else "Received error"
                print(f"{label}: {text}")
                replies += 1
            else:
                raise RuntimeError(f"unknown server message type: {message.get('type')}")


def main():
    parser = argparse.ArgumentParser(description="Send requests and distinguish responses from events")
    parser.add_argument("--server", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--message", action="append")
    parser.add_argument("--send-malformed", action="store_true")
    args = parser.parse_args()

    with socket.create_connection((args.server, args.port), timeout=5) as connection:
        messages = args.message or ["hello server", "second message"]
        payload = b"".join(
            encode_message({"type": "echo", "request_id": index, "text": message})
            for index, message in enumerate(messages, start=1)
        )
        if args.send_malformed:
            payload += b"{bad json}\n"

        for index, message in enumerate(messages, start=1):
            print(f"Sent request: {{'type': 'echo', 'request_id': {index}, 'text': {message!r}}}")
        connection.sendall(payload)
        receive_replies(connection, len(messages) + int(args.send_malformed))


if __name__ == "__main__":
    main()

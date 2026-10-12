"""Temporary manual client for testing A's server skeleton."""

import argparse
import json
import socket
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol import JsonLineBuffer, encode_message  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--id", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()

    stop_event = threading.Event()

    with socket.create_connection((args.server, args.port)) as connection:
        def receive() -> None:
            buffer = JsonLineBuffer()
            try:
                while not stop_event.is_set():
                    data = connection.recv(4096)
                    if not data:
                        break
                    for message in buffer.feed(data):
                        print(json.dumps(message, ensure_ascii=False), flush=True)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                print(f"receive error: {exc}", flush=True)
            finally:
                stop_event.set()

        threading.Thread(target=receive, daemon=True).start()
        connection.sendall(encode_message({
            "type": "hello",
            "request_id": "manual-hello-1",
            "user_id": args.id,
            "name": args.name,
        }))
        print("Temporary A-server test client. Commands: ping, quit", flush=True)
        while not stop_event.is_set():
            try:
                command = input("> ").strip()
            except EOFError:
                break
            if command == "ping":
                connection.sendall(encode_message({"type": "ping", "request_id": "manual-ping-1"}))
            elif command in {"quit", "exit"}:
                break
            elif command:
                print("Available commands: ping, quit", flush=True)
        stop_event.set()

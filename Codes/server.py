"""Minimal threaded TCP server skeleton for CSI201 CW1."""

import argparse
import json
import signal
import socket
import threading
from pathlib import Path

from protocol import JsonLineBuffer, encode_message


class ClientSession:
    def __init__(self, connection: socket.socket, address: tuple[str, int]) -> None:
        self.connection = connection
        self.address = address
        self.user_id: str | None = None
        self.name: str | None = None
        self.send_lock = threading.Lock()


class Server:
    def __init__(self, host: str, port: int, questions_path: Path) -> None:
        self.host = host
        self.port = port
        self.questions_path = questions_path
        self.listener: socket.socket | None = None
        self.bound_address: tuple[str, int] | None = None
        self.stop_event = threading.Event()
        self.sessions: dict[socket.socket, ClientSession] = {}
        self.sessions_lock = threading.Lock()

    def validate_questions_file(self) -> None:
        """Small startup hook; B can replace this with the full schema validator."""
        if not self.questions_path.is_file():
            raise ValueError(f"question bank not found: {self.questions_path}")
        if self.questions_path.stat().st_size == 0 or self.questions_path.stat().st_size > 1_000_000:
            raise ValueError("question bank must be between 1 byte and 1 MB")
        try:
            with self.questions_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid question bank: {exc}") from exc
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise ValueError("question bank schema_version must be 1")
        if not isinstance(data.get("quizzes"), list) or not data["quizzes"]:
            raise ValueError("question bank must contain quizzes")

    def start(self) -> None:
        self.validate_questions_file()
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind((self.host, self.port))
        self.listener.listen()
        self.listener.settimeout(0.5)
        self.bound_address = self.listener.getsockname()
        print("SERVER_READY", flush=True)

        while not self.stop_event.is_set():
            try:
                connection, address = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            session = ClientSession(connection, address)
            with self.sessions_lock:
                self.sessions[connection] = session
            thread = threading.Thread(target=self.handle_client, args=(session,), daemon=True)
            thread.start()

    def handle_client(self, session: ClientSession) -> None:
        buffer = JsonLineBuffer()
        connection = session.connection
        try:
            while not self.stop_event.is_set():
                data = connection.recv(4096)
                if not data:
                    break
                try:
                    messages = buffer.feed(data)
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                    self.send(session, self.error(None, "MALFORMED_MESSAGE", str(exc)))
                    break
                for message in messages:
                    self.dispatch(session, message)
        except OSError:
            pass
        finally:
            self.remove_session(session)

    def dispatch(self, session: ClientSession, message: dict) -> None:
        message_type = message.get("type")
        request_id = message.get("request_id")
        if not isinstance(message_type, str):
            self.send(session, self.error(request_id, "INVALID_MESSAGE", "type is required"))
            return
        if message_type == "hello":
            self.handle_hello(session, message)
            return
        if message_type == "ping":
            self.send(session, self.response(request_id, {"message": "pong"}))
            return
        self.send(session, self.error(request_id, "UNKNOWN_COMMAND", message_type))

    def handle_hello(self, session: ClientSession, message: dict) -> None:
        request_id = message.get("request_id")
        user_id = message.get("user_id")
        name = message.get("name")
        if not isinstance(user_id, str) or not isinstance(name, str) or not user_id or not name:
            self.send(session, self.error(request_id, "INVALID_IDENTITY", "user_id and name are required"))
            return
        with self.sessions_lock:
            duplicate = any(item.user_id == user_id for item in self.sessions.values() if item is not session)
            if not duplicate:
                session.user_id = user_id
                session.name = name
        if duplicate:
            self.send(session, self.error(request_id, "DUPLICATE_USER_ID", "user_id is already active"))
            return
        self.send(session, self.response(request_id, {"user_id": user_id, "name": name}))

    def send(self, session: ClientSession, message: dict) -> None:
        payload = encode_message(message)
        with session.send_lock:
            session.connection.sendall(payload)

    @staticmethod
    def response(request_id: object, data: dict) -> dict:
        return {"type": "response", "request_id": request_id, "ok": True, "data": data}

    @staticmethod
    def error(request_id: object, code: str, message: str) -> dict:
        return {"type": "response", "request_id": request_id, "ok": False, "error": {"code": code, "message": message}}

    def remove_session(self, session: ClientSession) -> None:
        with self.sessions_lock:
            self.sessions.pop(session.connection, None)
        try:
            session.connection.close()
        except OSError:
            pass

    def shutdown(self, *_: object) -> None:
        self.stop_event.set()
        with self.sessions_lock:
            sessions = list(self.sessions.values())
        for session in sessions:
            try:
                self.send(session, {"type": "server_shutdown", "reason": "server stopping"})
            except OSError:
                pass
            self.remove_session(session)
        if self.listener is not None:
            try:
                self.listener.close()
            except OSError:
                pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--questions", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = Server(args.host, args.port, Path(args.questions))
    signal.signal(signal.SIGINT, server.shutdown)
    try:
        server.start()
    except ValueError as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1) from exc
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()

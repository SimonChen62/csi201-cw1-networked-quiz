"""One-client scripted peer for E's UI tests, NOT the assessed B/C server.

The other room member is simulated. This is not evidence of real multi-user
rooms, complete question-bank validation, or the finished tournament system.
"""

import argparse
from pathlib import Path
import socket
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from protocol import encode_message, extract_messages, decode_message


class DemoSession:
    def __init__(self, sock, seconds=5):
        self.sock = sock
        self.seconds = seconds
        self.lock = threading.RLock()
        self.send_lock = threading.Lock()
        self.stop = threading.Event()
        self.timer = None
        self.user_id = None
        self.name = None
        self.in_room = False
        self.ready = False
        self.phase = "WAITING"
        self.answer = None
        self.deadline = None
        self.score = 0

    def send(self, message):
        with self.send_lock:
            try:
                self.sock.sendall(encode_message(message))
            except OSError:
                self.stop.set()

    def event(self, name, data):
        self.send({"type": "event", "event": name, "data": data})

    def room(self):
        return {
            "room_id": "DEMO-ROOM", "quiz_id": "demo-quiz",
            "host_user_id": self.user_id, "state": self.phase,
            "players": [
                {"user_id": self.user_id, "name": self.name, "ready": self.ready, "score": self.score},
                {"user_id": "demo_guest", "name": "Simulated guest", "ready": True, "score": 0},
            ],
        }

    def handle(self, request):
        request_id = request.get("request_id")

        def ok(data=None):
            self.send({"type": "response", "request_id": request_id, "ok": True, "data": data or {}})

        def error(code, message):
            self.send({"type": "response", "request_id": request_id, "ok": False,
                       "error": {"code": code, "message": message}})

        with self.lock:
            command = request.get("type")
            if command == "hello":
                self.user_id, self.name = request["user_id"], request["name"]
                ok()
                self.event("demo_notice", {"message": "Scripted one-client peer; demo_guest is simulated. This is not the assessed server."})
            elif command == "list_quizzes":
                ok({"quizzes": [{"quiz_id": "demo-quiz", "title": "CLI fixture", "description": "One scripted UI question", "question_count": 1}]})
            elif command == "list_rooms":
                ok({"rooms": [] if self.phase != "WAITING" else [self.room()]})
            elif command in ("create_room", "join_room"):
                expected = "demo-quiz" if command == "create_room" else "DEMO-ROOM"
                value = request.get("quiz_id" if command == "create_room" else "room_id")
                if value != expected:
                    error("ROOM_NOT_FOUND" if command == "join_room" else "QUIZ_NOT_FOUND", "Unknown demo fixture ID")
                elif self.phase != "WAITING":
                    error("ROOM_STARTED", "Restart this scripted peer for another run")
                else:
                    self.in_room = True
                    ok({"room": self.room()})
            elif command == "quit":
                ok()
                self.stop.set()
            elif not self.in_room or request.get("room_id") != "DEMO-ROOM":
                error("NOT_IN_ROOM", "Join the demo room first")
            elif command == "inspect_room":
                ok({"room": self.room()})
            elif command == "ready":
                self.ready = request.get("ready") is True
                ok({"room": self.room()})
                self.event("room_update", self.room())
            elif command == "start_game":
                if self.phase != "WAITING":
                    error("INVALID_STATE", "Quiz already started")
                elif not self.ready:
                    error("PLAYERS_NOT_READY", "Use ready first")
                else:
                    self.phase = "RUNNING"
                    self.deadline = time.monotonic() + self.seconds
                    ok()
                    self.event("room_update", self.room())
                    self.event("question", {
                        "room_id": "DEMO-ROOM", "question_id": "DEMO-Q1", "question_index": 0,
                        "text": "Which protocol provides a reliable byte stream?",
                        "options": {"A": "UDP", "B": "TCP", "C": "ARP", "D": "ICMP"},
                        "time_limit": self.seconds, "points": 100,
                    })
                    self.timer = threading.Timer(self.seconds, self.finish)
                    self.timer.daemon = True
                    self.timer.start()
            elif command == "answer":
                if self.phase != "RUNNING" or time.monotonic() >= self.deadline:
                    error("QUESTION_CLOSED", "Question is closed")
                elif request.get("question_id") != "DEMO-Q1" or request.get("answer") not in ("A", "B", "C", "D"):
                    error("INVALID_ANSWER", "Invalid question ID or option")
                elif self.answer is not None:
                    error("DUPLICATE_ANSWER", "An answer was already accepted")
                else:
                    self.answer = request["answer"]
                    ok({"accepted": True, "question_id": "DEMO-Q1"})
            elif command == "leave_room":
                self.in_room = False
                ok()
            else:
                error("UNKNOWN_COMMAND", "Unsupported scripted command")

    def finish(self):
        with self.lock:
            if self.stop.is_set() or not self.in_room:
                return
            self.phase = "FINISHED"
            self.score = 100 if self.answer == "B" else 0
            self.event("question_result", {
                "room_id": "DEMO-ROOM", "question_id": "DEMO-Q1", "answer": "B",
                "scores": {self.user_id: self.score, "demo_guest": 0},
            })
            self.event("leaderboard", {
                "room_id": "DEMO-ROOM",
                "leaderboard": [
                    {"rank": 1, "user_id": self.user_id, "name": self.name, "score": self.score},
                    {"rank": 2, "user_id": "demo_guest", "name": "Simulated guest", "score": 0},
                ],
            })

    def run(self):
        self.sock.settimeout(0.2)
        buffer = bytearray()
        try:
            while not self.stop.is_set():
                try:
                    chunk = self.sock.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buffer.extend(chunk)
                for frame in extract_messages(buffer):
                    self.handle(decode_message(frame))
        finally:
            self.stop.set()
            if self.timer is not None:
                self.timer.cancel()
                self.timer.join(timeout=1)
            self.sock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--question-seconds", type=int, default=5)
    args = parser.parse_args()
    if not 5 <= args.question_seconds <= 60:
        parser.error("--question-seconds must be 5 to 60")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((args.host, args.port))
        listener.listen(1)
        print(f"DEMO_LISTENING {args.host} {listener.getsockname()[1]}", flush=True)
        sock, _ = listener.accept()
        DemoSession(sock, args.question_seconds).run()


if __name__ == "__main__":
    main()

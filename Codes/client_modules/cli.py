"""E's text UI. Blocking keyboard and request work never runs on the UI loop."""

import codecs
from collections import deque
import os
import queue
import shlex
import sys
import threading

from .connection import Connection
from .state import ClientState


HELP = """Commands:
  help                         Show this help
  quizzes                      List public quiz information
  rooms                        List joinable rooms
  create <quiz_id>              Create a room
  join <room_id>                Join a room
  players                      Inspect your room and readiness
  ready [on|off]                Set readiness (default: on)
  start                        Ask the server to start the quiz
  answer <question_id> <A|B|C|D> Submit for the named question
  score                        Show the last server-confirmed scores
  status                       Show your current state
  leave                        Leave your room
  quit                         Close the client
Timing and scoring are decided by the server."""


def parse_command(line, snapshot):
    """Return a local action or a request plus explicit room/question context."""
    parts = shlex.split(line)
    if not parts:
        return None
    command, args = parts[0].lower(), parts[1:]
    counts = {
        "help": (0,), "status": (0,), "score": (0,), "quit": (0,),
        "quizzes": (0,), "rooms": (0,), "create": (1,), "join": (1,),
        "players": (0,), "ready": (0, 1), "start": (0,), "answer": (2,), "leave": (0,),
    }
    if command not in counts:
        raise ValueError("Unknown command. Type help.")
    if len(args) not in counts[command]:
        raise ValueError("Wrong arguments. Type help; answers require a question ID.")
    if command in ("help", "status", "score", "quit"):
        return command, {}
    if not snapshot["connected"]:
        raise ValueError("Wait for login to complete.")
    if command in ("quizzes", "rooms"):
        return "list_" + command, {}
    if command in ("create", "join"):
        if snapshot["current_room_id"] is not None:
            raise ValueError("Leave your current room first.")
        key = "quiz_id" if command == "create" else "room_id"
        return command + "_room", {key: args[0]}
    room_id = snapshot["current_room_id"]
    if room_id is None:
        raise ValueError("Join or create a room first.")
    data = {"room_id": room_id}
    if command == "players":
        return "inspect_room", data
    if command == "ready":
        value = args[0].lower() if args else "on"
        if value not in ("on", "off"):
            raise ValueError("Use ready on or ready off.")
        return "ready", {**data, "ready": value == "on"}
    if command == "start":
        return "start_game", data
    if command == "leave":
        return "leave_room", data
    question = snapshot["current_question"]
    if question is None or args[0] != question["id"]:
        raise ValueError("That question is not open. Use the ID printed with the current question.")
    answer = args[1].upper()
    if answer not in ("A", "B", "C", "D"):
        raise ValueError("Answer must be A, B, C or D.")
    return "answer", {**data, "question_id": args[0], "answer": answer}


class InputReader(threading.Thread):
    """Read bytes without holding Python's buffered stdin lock during shutdown."""

    def __init__(self, stream, messages):
        super().__init__(daemon=True)
        self.stream = stream
        self.messages = messages

    def run(self):
        try:
            try:
                descriptor = self.stream.fileno()
            except (AttributeError, OSError):
                for line in self.stream:
                    self.messages.put(line.rstrip("\r\n"))
                return
            decoder = codecs.getincrementaldecoder(self.stream.encoding or "utf-8")(errors="replace")
            buffer = ""
            while True:
                chunk = os.read(descriptor, 4096)
                if not chunk:
                    buffer += decoder.decode(b"", final=True)
                    if buffer:
                        self.messages.put(buffer.rstrip("\r"))
                    break
                buffer += decoder.decode(chunk)
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    self.messages.put(line.rstrip("\r"))
        except OSError:
            pass
        finally:
            self.messages.put(None)


class RequestWorker(threading.Thread):
    def __init__(self, connection, address, results):
        super().__init__(daemon=True)
        self.connection = connection
        self.address = address
        self.results = results
        self.tasks = queue.Queue()

    def run(self):
        ok = self.connection.connect(*self.address)
        self.results.put(("connect", {}, {"ok": ok, "error": self.connection.last_error}))
        if not ok:
            return
        while True:
            task = self.tasks.get()
            if task is None:
                return
            command, data = task
            response = self.connection.send_request(command, data, timeout=1 if command == "quit" else 5)
            self.results.put((command, data, response))
            if command == "quit":
                return


class QuizCLI:
    def __init__(self, connection, state, address, stdin=None, stdout=None):
        self.connection, self.state, self.address = connection, state, address
        self.stdin, self.stdout = stdin or sys.stdin, stdout or sys.stdout
        self.inputs, self.results = queue.Queue(maxsize=128), queue.Queue()
        self.worker = RequestWorker(connection, address, self.results)
        self.commands = deque()
        self.busy = "connect"
        self.eof = False
        self.closing = False
        self.done = False
        self.exit_code = 0
        self.prompt_visible = False
        self.interactive = self.stdin.isatty()

    def write(self, text):
        # All terminal output, including errors, goes through this one UI thread.
        text = "".join(c if c in "\n\t" or ord(c) >= 32 and ord(c) != 127 else "?" for c in str(text))
        if self.prompt_visible:
            self.stdout.write("\n")
        self.stdout.write(text + "\n")
        self.stdout.flush()
        self.prompt_visible = False

    def run(self):
        self.write("Networked Quiz Tournament | Type help for commands.")
        self.write(f"Connecting to {self.address[0]}:{self.address[1]} ...")
        self.worker.start()
        InputReader(self.stdin, self.inputs).start()
        try:
            while not self.done:
                self._drain_events()
                self._drain_results()
                if self.done:
                    break
                try:
                    line = self.inputs.get(timeout=0.05)
                    if line is None:
                        self.eof = True
                    elif len(self.commands) < 32:
                        self.commands.append(line)
                    else:
                        self.write("[ERROR] Too many queued commands.")
                except queue.Empty:
                    pass
                if self.commands:
                    first_word = self.commands[0].split(maxsplit=1)
                    local = bool(first_word) and first_word[0].lower() in ("help", "status", "score", "quit")
                    if self.busy is None or local:
                        line = self.commands.popleft()
                        self.prompt_visible = False
                        self._execute(line)
                elif self.eof and self.busy is None and not self.closing:
                    self._quit()
                if self.interactive and not self.prompt_visible and not self.done:
                    self.stdout.write("> ")
                    self.stdout.flush()
                    self.prompt_visible = True
        except KeyboardInterrupt:
            self.write("Interrupted. Closing client.")
        finally:
            self.connection.disconnect()
            self.worker.tasks.put(None)
            self.worker.join(timeout=1)
        return self.exit_code

    def _execute(self, line):
        try:
            action = parse_command(line, self.state.get_snapshot())
            if action is None:
                return
            command, data = action
            if command == "help":
                self.write(HELP)
            elif command == "status":
                state = self.state.get_snapshot()
                self.write(f"[STATUS] user={state['user_id']} room={state['current_room_id']} phase={state['room_phase']}")
            elif command == "score":
                self._show_scores()
            elif command == "quit":
                self._quit()
            else:
                self.busy = command
                self.worker.tasks.put((command, data))
        except (ValueError, TypeError) as exc:
            self.write(f"[ERROR] {exc}")

    def _quit(self):
        self.closing = True
        if self.busy is not None or not self.state.get_snapshot()["connected"]:
            self.write("Closing client.")
            self.done = True
        else:
            self.busy = "quit"
            self.worker.tasks.put(("quit", {}))

    def _drain_results(self):
        while True:
            try:
                command, sent, response = self.results.get_nowait()
            except queue.Empty:
                return
            self.busy = None
            if command == "connect":
                if response["ok"]:
                    self.write(f"[CONNECTED] {self.address[3]} ({self.address[2]})")
                else:
                    error = response.get("error") or {}
                    error = error.get("error", {"code": "CONNECT_FAILED", "message": "Connection closed during login"})
                    self.write(f"[ERROR] {error['code']}: {error['message']}")
                    self.exit_code, self.done = 1, True
            elif command == "quit":
                self.write("Goodbye.")
                self.done = True
            elif not response.get("ok"):
                error = response.get("error", {})
                self.write(f"[ERROR] {error.get('code', 'REQUEST_FAILED')}: {error.get('message', 'Request rejected')}")
            else:
                self._show_response(command, sent, response.get("data", {}))

    def _show_response(self, command, sent, data):
        if command == "list_quizzes":
            quizzes = data.get("quizzes", [])
            self.write("[QUIZZES]")
            for quiz in quizzes:
                self.write(f"  {quiz['quiz_id']} | {quiz['title']} | {quiz['question_count']} questions")
                if quiz.get("description"):
                    self.write("    " + quiz["description"])
            if not quizzes:
                self.write("  No quizzes available.")
        elif command == "list_rooms":
            self.write("[ROOMS]")
            for room in data.get("rooms", []):
                self.write(f"  {room['room_id']} | quiz={room.get('quiz_id', '?')} | {room.get('state', 'WAITING')}")
            if not data.get("rooms"):
                self.write("  No joinable rooms. Use create <quiz_id>.")
        elif command in ("create_room", "join_room", "inspect_room", "ready"):
            self._show_room()
        elif command == "answer":
            if data.get("accepted", True):
                self.write(f"[ANSWER {sent['question_id']}] Submission accepted. Result follows when the question closes.")
            else:
                self.write(f"[ANSWER {sent['question_id']}] Submission was not accepted.")
        elif command == "start_game":
            self.write("[START] Request accepted. Waiting for the server's question.")
        elif command == "leave_room":
            self.write("[LOBBY] Left the room.")

    def _drain_events(self):
        while True:
            try:
                message = self.connection.event_queue.get_nowait()
            except queue.Empty:
                return
            if message.get("type") == "client_notice":
                self.write(f"[NOTICE] {message.get('code')}: {message.get('message')}")
                continue
            event, data = message.get("event"), message.get("data", {})
            if event == "server_shutdown":
                if self.busy == "connect":
                    continue  # The connect result carries the precise login error.
                self.write(f"[DISCONNECTED] {data.get('reason', 'Server closed the connection')}")
                self.done = True
            elif event == "room_update":
                self._show_room()
            elif event == "question":
                self.write(f"[QUESTION {data['question_id']}] {data['text']}")
                for option in ("A", "B", "C", "D"):
                    self.write(f"  {option}. {data.get('options', {}).get(option, '')}")
                self.write(f"Limit: {data['time_limit']} seconds | Points: {data['points']}")
                self.write(f"Use: answer {data['question_id']} <A|B|C|D>")
            elif event == "question_result":
                uid = self.address[2]
                total = data.get("scores", {}).get(uid, 0)
                self.write(f"[RESULT {data['question_id']}] Correct: {data['answer']} | Your total: {total}")
            elif event == "leaderboard":
                self.write("[LEADERBOARD]")
                for index, player in enumerate(data.get("leaderboard", []), 1):
                    self.write(f"  {player.get('rank', index)}. {player.get('name', player['user_id'])} | {player['score']}")
                self.write("Quiz finished. Use leave or quit.")
            elif event == "demo_notice":
                self.write("[DEMO] " + data.get("message", "Scripted test peer."))

    def _show_room(self):
        state = self.state.get_snapshot()
        self.write(f"[ROOM {state['current_room_id']}] quiz={state['quiz_id']} state={state['room_phase']} host={state['host_user_id']}")
        for uid, player in state["players"].items():
            self.write(f"  {uid} | {player['name']} | ready={player['ready']} | score={player['score']}")

    def _show_scores(self):
        state = self.state.get_snapshot()
        self.write("[SCORES] Last values confirmed by the server")
        for uid, player in state["players"].items():
            self.write(f"  {uid} | {player['name']} | {player['score']}")
        if not state["players"]:
            self.write("  No room scores available.")


def run_client(host, port, user_id, name, stdin=None, stdout=None):
    state = ClientState()
    connection = Connection(state)
    return QuizCLI(connection, state, (host, port, user_id, name), stdin, stdout).run()

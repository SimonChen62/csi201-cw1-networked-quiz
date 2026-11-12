"""Run the real client process against the explicitly scripted CLI test peer."""

import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import unittest

CODES = Path(__file__).resolve().parents[1]


class CapturedProcess:
    def __init__(self, arguments, environment):
        self.process = subprocess.Popen(
            arguments, cwd=CODES, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", bufsize=1, env=environment,
        )
        self.lines = queue.Queue()
        self.history = []
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        for line in self.process.stdout:
            self.history.append(line.rstrip("\n"))
            self.lines.put(line)

    def wait_for(self, text, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self.lines.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            if text in line:
                return line
        raise AssertionError(f"Did not receive {text!r}.\n" + "\n".join(self.history[-100:]))

    def send(self, command):
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=3)
        self.reader.join(timeout=1)
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()
        self.process.stdout.close()


class ClientProcessTest(unittest.TestCase):
    def setUp(self):
        environment = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
                           PYTHONDONTWRITEBYTECODE="1")
        self.server = CapturedProcess(
            [sys.executable, "-u", "tests/cli_demo_server.py", "--port", "0"], environment
        )
        self.addCleanup(self.server.close)
        line = self.server.wait_for("DEMO_LISTENING", timeout=5)
        port = line.split()[-1]
        self.client = CapturedProcess([
            sys.executable, "-u", "client.py", "--server", "127.0.0.1", "--port", port,
            "--id", "u1", "--name", "Alice",
        ], environment)
        self.addCleanup(self.client.close)
        self.client.wait_for("[CONNECTED]")

    def test_cli_workflow_errors_and_results_while_stdin_is_idle(self):
        client = self.client
        client.send("quizzes")
        client.wait_for("demo-quiz | CLI fixture")
        client.send("join missing")
        client.wait_for("[ERROR] ROOM_NOT_FOUND")
        client.send("create demo-quiz")
        client.wait_for("[ROOM DEMO-ROOM]")
        client.send("start")
        client.wait_for("[ERROR] PLAYERS_NOT_READY")
        client.send("ready")
        client.wait_for("u1 | Alice | ready=True")
        client.send("start")
        client.wait_for("Use: answer DEMO-Q1")
        client.send("answer OLD-Q B")
        client.wait_for("That question is not open")
        client.send("answer DEMO-Q1 B")
        client.wait_for("[ANSWER DEMO-Q1] Submission accepted.")
        self.assertFalse(any("[RESULT " in line for line in client.history))
        client.send("answer DEMO-Q1 A")
        client.wait_for("[ERROR] DUPLICATE_ANSWER")
        # Deliberately send no newline/input while the timer closes the question.
        client.wait_for("[RESULT DEMO-Q1] Correct: B | Your total: 100")
        client.wait_for("[LEADERBOARD]")
        client.wait_for("1. Alice | 100")
        client.send("leave")
        client.wait_for("[LOBBY] Left the room.")
        client.send("quit")
        self.assertEqual(client.process.wait(timeout=3), 0)

    def test_remote_disconnect_exits_without_another_enter(self):
        self.server.process.terminate()
        self.server.process.wait(timeout=3)
        self.client.wait_for("[DISCONNECTED]", timeout=3)
        self.assertEqual(self.client.process.wait(timeout=3), 0)

    def test_stdin_eof_closes_client(self):
        self.client.process.stdin.close()
        self.assertEqual(self.client.process.wait(timeout=3), 0)


if __name__ == "__main__":
    unittest.main()

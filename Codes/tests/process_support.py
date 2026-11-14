"""Bounded process capture for real paired-system acceptance tests."""
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time

CODES = Path(__file__).resolve().parents[1]


class ProcessCapture:
    def __init__(self, arguments, label, evidence=None):
        self.label, self.evidence = label, evidence
        self.history = []
        self.condition = threading.Condition()
        self.process = subprocess.Popen(
            arguments, cwd=CODES, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", bufsize=1,
            env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
                     PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1"),
        )
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        for line in self.process.stdout:
            with self.condition:
                self.history.append(line.rstrip("\n"))
                self.condition.notify_all()

    def mark(self):
        with self.condition:
            return len(self.history)

    def wait_for(self, text, *, after=0, timeout=10):
        deadline = time.monotonic() + timeout
        with self.condition:
            while True:
                for line in self.history[after:]:
                    if text in line:
                        return line
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AssertionError(f"{self.label}: missing {text!r}\n" + "\n".join(self.history[-60:]))
                self.condition.wait(remaining)

    def send(self, command):
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()

    def command(self, command, expected):
        mark = self.mark()
        self.send(command)
        return self.wait_for(expected, after=mark)

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.reader.join(timeout=2)
        if self.evidence is not None:
            self.evidence.mkdir(parents=True, exist_ok=True)
            (self.evidence / f"{self.label}.txt").write_text(
                "\n".join(self.history) + f"\nPROCESS_EXIT={self.process.returncode}\n", encoding="utf-8")
        self.process.stdin.close()
        self.process.stdout.close()


class WirePeer:
    """Adversarial test driver, distinct from the submitted CLI client."""
    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        self.buffer = bytearray()
        self.messages = []
        self.request_id = 0

    def wait(self, predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while True:
            for index, message in enumerate(self.messages):
                if predicate(message):
                    return self.messages.pop(index)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError("No matching wire message")
            self.sock.settimeout(remaining)
            chunk = self.sock.recv(4096)
            if not chunk:
                raise AssertionError("Server closed before expected response")
            self.buffer.extend(chunk)
            while b"\n" in self.buffer:
                line, _, tail = self.buffer.partition(b"\n")
                self.buffer = bytearray(tail)
                self.messages.append(json.loads(line))

    def request(self, command, **fields):
        self.request_id += 1
        request_id = str(self.request_id)
        self.sock.sendall((json.dumps(dict(type=command, request_id=request_id, **fields)) + "\n").encode())
        return self.wait(lambda message: message.get("type") == "response" and message.get("request_id") == request_id)

    def event(self, name, question_id=None, timeout=8):
        return self.wait(lambda message: message.get("event") == name and (
            question_id is None or message.get("data", {}).get("question_id") == question_id), timeout)

    def close(self):
        self.sock.close()

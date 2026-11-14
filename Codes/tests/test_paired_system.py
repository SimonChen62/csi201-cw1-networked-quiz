"""Real server.py + client.py processes; no replacement business server.

The harness supplies terminal input, knows expected answers for assertions and
optionally captures transcripts. The actual client never opens a question bank.
"""
import json
import os
from pathlib import Path
import re
import signal
import socket
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from process_support import CODES, ProcessCapture, WirePeer


class PairedSystemTest(unittest.TestCase):
    def setUp(self):
        evidence = os.environ.get("QUIZ_EVIDENCE_DIR")
        self.evidence = Path(evidence) / self._testMethodName if evidence else None
        self.bank = json.loads((CODES / "questions.json").read_text(encoding="utf-8"))
        self.server = None
        self.clients = []

    def start_server(self, *, short_deadlines=False, filename="questions.json"):
        path = CODES / filename
        self.bank = json.loads(path.read_text(encoding="utf-8"))
        if short_deadlines:
            temporary = tempfile.TemporaryDirectory()
            self.addCleanup(temporary.cleanup)
            for quiz in self.bank["quizzes"]:
                for question in quiz["questions"]:
                    question["time_limit"] = 5  # Normative minimum, not an engine test override.
            path = Path(temporary.name) / "acceptance.json"
            path.write_text(json.dumps(self.bank), encoding="utf-8")
        if self.evidence:
            self.evidence.mkdir(parents=True, exist_ok=True)
            (self.evidence / "question-bank.json").write_bytes(path.read_bytes())
        self.server = ProcessCapture([
            sys.executable, "-B", "server.py", "--host", "127.0.0.1", "--port", "0",
            "--questions", str(path),
        ], "server", self.evidence)
        self.addCleanup(self.server.close)
        self.port = int(self.server.wait_for("SERVER_READY").split()[-1])

    def client(self, user_id, *, login=True, label=None):
        client = ProcessCapture([
            sys.executable, "-B", "client.py", "--server", "127.0.0.1", "--port", str(self.port),
            "--id", user_id, "--name", user_id,
        ], label or user_id, self.evidence)
        self.clients.append(client)
        self.addCleanup(client.close)
        if login:
            client.wait_for("[CONNECTED]")
        return client

    def room(self, clients, quiz):
        line = clients[0].command("create " + quiz["quiz_id"], "[ROOM ")
        room_id = re.search(r"\[ROOM ([^]]+)\]", line).group(1)
        for client in clients[1:]:
            client.command("join " + room_id, f"[ROOM {room_id}]")
        return room_id

    def ready(self, clients):
        for client in clients:
            client.command("ready", f"{client.label} | {client.label} | ready=True")

    def start(self, clients, quiz):
        clients[0].command("start", "[START] Request accepted")
        for client in clients:
            client.wait_for("Use: answer " + quiz["questions"][0]["question_id"])

    def answer_round(self, clients, question, *, correct):
        answer = question["answer"] if correct else next(key for key in "ABCD" if key != question["answer"])
        for client in clients:
            client.wait_for("Use: answer " + question["question_id"])
            client.send(f"answer {question['question_id']} {answer}")
        for client in clients:
            client.wait_for(f"[RESULT {question['question_id']}]")

    def stop_server(self):
        self.server.process.send_signal(signal.SIGINT)
        self.assertEqual(self.server.process.wait(timeout=8), 0)
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", self.port), timeout=1)

    def test_two_real_cli_clients_complete_shipped_quiz(self):
        self.start_server()
        alice, bob = self.client("alice"), self.client("bob")
        duplicate = self.client("alice", login=False, label="duplicate-alice")
        duplicate.wait_for("[ERROR] DUPLICATE_USER")
        self.assertEqual(duplicate.process.wait(timeout=4), 1)
        quiz = self.bank["quizzes"][0]
        alice.command("quizzes", quiz["quiz_id"] + " |")
        alice.command("create missing", "[ERROR] QUIZ_NOT_FOUND")
        self.room([alice, bob], quiz)
        bob.command("start", "[ERROR] NOT_HOST")
        alice.command("start", "[ERROR] NOT_ALL_READY")
        self.ready([alice, bob])
        self.start([alice, bob], quiz)
        total = 0
        for index, question in enumerate(quiz["questions"]):
            qid = question["question_id"]
            for client in (alice, bob):
                client.wait_for("Use: answer " + qid)
            alice.command(f"answer {qid} {question['answer']}", f"[ANSWER {qid}] Submission accepted")
            if index == 0:
                self.assertFalse(any("[RESULT " in line for line in alice.history))
                alice.command(f"answer {qid} {question['answer']}", "[ERROR] DUPLICATE_ANSWER")
            wrong = next(key for key in "ABCD" if key != question["answer"])
            bob.send(f"answer {qid} {wrong}")
            total += question["points"]
            alice.wait_for(f"[RESULT {qid}] Correct: {question['answer']} | Your total: {total}")
            bob.wait_for(f"[RESULT {qid}] Correct: {question['answer']} | Your total: 0")
        for client in (alice, bob):
            client.wait_for("[LEADERBOARD]")
            client.wait_for(f"1. alice | {total}")
            client.wait_for("2. bob | 0")
            client.command("leave", "[LOBBY] Left the room")
            client.command("quit", "Goodbye")
            self.assertEqual(client.process.wait(timeout=4), 0)
        self.stop_server()

    def test_teacher_fifty_question_bank_supports_formal_login(self):
        self.start_server(filename="questions_50.json")
        client = self.client("teacher-bank-check")
        client.command("quizzes", "[QUIZZES]")
        for quiz in self.bank["quizzes"]:
            client.wait_for(f"{quiz['quiz_id']} | {quiz['title']} | 10 questions")
        self.assertEqual(len(self.bank["quizzes"]), 5)
        self.stop_server()
        client.wait_for("[DISCONNECTED]")
        self.assertEqual(client.process.wait(timeout=4), 0)

    def test_ten_real_cli_clients_two_rooms_isolation_and_disconnect(self):
        self.run_two_rooms(drop_player=True)

    def test_ten_real_cli_clients_complete_both_rooms(self):
        self.run_two_rooms(drop_player=False)

    def run_two_rooms(self, *, drop_player):
        self.start_server(short_deadlines=True)
        group_a = [self.client(f"a{index}") for index in range(5)]
        group_b = [self.client(f"b{index}") for index in range(5)]
        quiz_a, quiz_b = self.bank["quizzes"]
        self.room(group_a, quiz_a)
        self.room(group_b, quiz_b)
        self.ready(group_a)
        self.ready(group_b)
        self.start(group_a, quiz_a)
        self.start(group_b, quiz_b)
        self.assertTrue(all(client.process.poll() is None for client in group_a + group_b))
        self.answer_round(group_a, quiz_a["questions"][0], correct=True)
        group_a[0].wait_for("Use: answer " + quiz_a["questions"][1]["question_id"])
        self.assertFalse(any("[RESULT " in line for client in group_b for line in client.history))
        if drop_player:
            dropped = group_b.pop()
            dropped.process.kill()
            dropped.process.wait(timeout=3)
        self.answer_round(group_b, quiz_b["questions"][0], correct=False)
        for index in range(1, 5):
            self.answer_round(group_a, quiz_a["questions"][index], correct=True)
            self.answer_round(group_b, quiz_b["questions"][index], correct=False)
        total = sum(question["points"] for question in quiz_a["questions"])
        for group, quiz, forbidden_prefix, score in (
            (group_a, quiz_a, "PYNET", total), (group_b, quiz_b, "NET", 0),
        ):
            expected = [question["question_id"] for question in quiz["questions"]]
            for client in group:
                client.wait_for("Quiz finished.")
                seen = [re.match(r"\[QUESTION ([^]]+)\]", line).group(1)
                        for line in client.history if line.startswith("[QUESTION ")]
                self.assertEqual(seen, expected)
                self.assertFalse(any(line.startswith(f"[RESULT {forbidden_prefix}") for line in client.history))
                client.wait_for(f"{client.label} | {score}")
                client.command("quit", "Goodbye")
                self.assertEqual(client.process.wait(timeout=4), 0)
        self.stop_server()

    def test_deadline_bad_messages_and_sigint_during_active_game(self):
        self.start_server(short_deadlines=True)
        observer = self.client("observer")
        peers = [WirePeer(self.port), WirePeer(self.port)]
        for peer in peers:
            self.addCleanup(peer.close)
        for index, peer in enumerate(peers):
            self.assertTrue(peer.request("hello", user_id=f"wire{index}", name=f"Wire {index}")["ok"])
        peer, other = peers
        for payload in (b"not-json\n", b'{"value":NaN}\n', b'{"nested":' + b"[" * 1100 + b"0" + b"]" * 1100 + b"\n"):
            peer.sock.sendall(payload)
            failure = peer.wait(lambda message: message.get("type") == "response" and message.get("request_id") is None)
            self.assertEqual(failure["error"]["code"], "MALFORMED_MESSAGE")
        self.assertEqual(peer.request("unknown")["error"]["code"], "UNKNOWN_COMMAND")
        quiz = self.bank["quizzes"][0]
        catalog = peer.request("list_quizzes")["data"]["quizzes"]
        self.assertTrue(all(set(item) == {"quiz_id", "title", "description", "question_count"} for item in catalog))
        room_id = peer.request("create_room", quiz_id=quiz["quiz_id"])["data"]["room"]["room_id"]
        self.assertTrue(other.request("join_room", room_id=room_id)["ok"])
        for player in peers:
            self.assertTrue(player.request("ready", room_id=room_id, ready=True)["ok"])
        started = time.monotonic()
        self.assertTrue(peer.request("start_game", room_id=room_id)["ok"])
        question = quiz["questions"][0]
        public = peer.event("question", question["question_id"])["data"]
        self.assertNotIn("answer", public)
        self.assertNotIn("correct", public)
        self.assertTrue(peer.request("answer", room_id=room_id, question_id=question["question_id"], choice=question["answer"])["ok"])
        result = peer.event("question_result", question["question_id"])["data"]
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 4.8)
        self.assertLess(elapsed, 8)
        self.assertEqual(result["scores"], {"wire0": question["points"], "wire1": 0})
        rejected = other.request("answer", room_id=room_id, question_id=question["question_id"], choice=question["answer"])
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["error"]["code"], "INVALID_MESSAGE")
        peer.sock.sendall(b"x" * (65536 + 1))
        too_large = peer.wait(lambda message: message.get("type") == "response" and message.get("request_id") is None)
        self.assertEqual(too_large["error"]["code"], "MESSAGE_TOO_LARGE")
        self.assertTrue(other.request("inspect_room", room_id=room_id)["ok"])
        if self.evidence:
            (self.evidence / "checks.txt").write_text(
                f"Deadline observed: {elapsed:.3f}s (configured 5s)\n"
                "Public catalog/question hide answers; malformed JSON/NaN/nested malformed JSON rejected.\n"
                "Missing answer scored zero; closed-question submission rejected; oversized peer isolated.\n",
                encoding="utf-8")
        self.stop_server()
        observer.wait_for("[DISCONNECTED]")
        self.assertEqual(observer.process.wait(timeout=4), 0)


if __name__ == "__main__":
    unittest.main()

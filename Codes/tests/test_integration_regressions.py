"""Regressions at the bank/lobby/engine/network integration boundaries."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import server
from server_modules.game_engine import GameEngine
from server_modules.lobby import Lobby
from server_modules.question_bank import MAX_FILE_BYTES, load_question_bank
from test_lobby import FakeSession, call
from test_question_bank import minimal_bank


class BankIntegrationTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "bank.json"

    def write(self, bank):
        self.path.write_text(json.dumps(bank), encoding="utf-8")

    def test_bom_order_extensions_and_exact_size_limit(self):
        bank = minimal_bank()
        bank["extra"] = {"revision": 1.5}
        bank["quizzes"][0]["questions"].reverse()
        self.write(bank)
        raw = b"\xef\xbb\xbf" + self.path.read_bytes()
        self.path.write_bytes(raw + b" " * (MAX_FILE_BYTES - len(raw)))
        loaded = load_question_bank(self.path)
        self.assertEqual([q.question_id for q in loaded.quizzes[0].questions], ["Q5", "Q4", "Q3", "Q2", "Q1"])
        with self.path.open("ab") as output:
            output.write(b" ")
        with self.assertRaises(ValueError):
            load_question_bank(self.path)

    def test_text_limits_include_spaces_and_reject_control_or_invalid_unicode(self):
        for text in ("A " * 51, "line\nbreak", "bad\x00text", "\ud800"):
            with self.subTest(text=repr(text)):
                bank = minimal_bank()
                bank["quizzes"][0]["title"] = text
                self.write(bank)
                with self.assertRaises(ValueError):
                    load_question_bank(self.path)

    def test_nonstandard_and_deeply_nested_malformed_json_have_meaningful_errors(self):
        # Nesting alone may be valid on this Python build; omit a closing bracket
        # to test a genuinely malformed input regardless of the parser limit.
        for raw in (b'{"x":NaN}', b'{"x":Infinity}', b"[" * 1500 + b"0" + b"]" * 1499):
            self.path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                load_question_bank(self.path)

    def test_invalid_last_question_prevents_any_socket_creation(self):
        bank = minimal_bank()
        bank["quizzes"][0]["questions"][-1]["points"] = 1001
        self.write(bank)
        output = io.StringIO()
        with mock.patch.object(server.socket, "socket") as socket_factory, contextlib.redirect_stdout(output):
            result = server.main(["--host", "127.0.0.1", "--port", "0", "--questions", str(self.path)])
        self.assertEqual(result, 1)
        socket_factory.assert_not_called()
        self.assertIn("questions[4]", output.getvalue())
        self.assertNotIn("SERVER_READY", output.getvalue())


class LobbyIntegrationTest(unittest.TestCase):
    def setUp(self):
        bank = load_question_bank(Path(__file__).resolve().parents[1] / "questions.json")
        self.lobby = Lobby(bank)
        self.addCleanup(self.lobby.shutdown)
        self.sessions = [FakeSession(f"s{i}") for i in range(3)]
        self.handler = self.lobby.handle_request
        for index, session in enumerate(self.sessions):
            self.assertTrue(call(self.handler, session, "hello", user_id=f"u{index}", name=f"User {index}")["ok"])
        response = call(self.handler, self.sessions[0], "create_room", quiz_id="network-basics")
        self.room_id = response["data"]["room"]["room_id"]
        call(self.handler, self.sessions[1], "join_room", room_id=self.room_id)
        for session in self.sessions[:2]:
            call(self.handler, session, "ready", room_id=self.room_id, ready=True)

    def test_start_reservation_rejects_join_and_ready_before_engine_runs(self):
        entered, release = threading.Event(), threading.Event()
        original = self.lobby._engine.start_match
        results = []

        def held_start(match):
            entered.set()
            if not release.wait(3):
                raise AssertionError("test did not release start")
            return original(match)

        with mock.patch.object(self.lobby._engine, "start_match", side_effect=held_start):
            worker = threading.Thread(target=lambda: results.append(call(self.handler, self.sessions[0], "start_game", room_id=self.room_id)))
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                for session, command, fields in (
                    (self.sessions[2], "join_room", {}),
                    (self.sessions[1], "ready", {"ready": False}),
                ):
                    rejected = call(self.handler, session, command, room_id=self.room_id, **fields)
                    self.assertEqual(rejected["error"]["code"], "ALREADY_STARTED")
            finally:
                release.set()
                worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertTrue(results[0]["ok"])

    def test_failed_event_recipient_does_not_prevent_other_players_receiving_question(self):
        with mock.patch.object(self.sessions[1], "send_event", side_effect=OSError("peer closed")), \
             mock.patch.object(self.sessions[1], "close") as closed:
            response = call(self.handler, self.sessions[0], "start_game", room_id=self.room_id)
        self.assertTrue(response["ok"])
        closed.assert_called()
        self.assertIsNotNone(self.sessions[0].last_event("question"))

    def test_shutdown_stops_timer_even_after_room_was_deleted(self):
        self.assertTrue(call(self.handler, self.sessions[0], "start_game", room_id=self.room_id)["ok"])
        match = self.lobby._rooms[self.room_id].match
        for session in self.sessions[:2]:
            self.lobby.on_disconnect(session)
        self.assertNotIn(self.room_id, self.lobby._rooms)
        self.lobby.shutdown()
        self.assertFalse(match.game_thread.is_alive())
        self.assertEqual(call(self.handler, self.sessions[2], "list_rooms")["error"]["code"], "SERVER_SHUTDOWN")

    def test_stopped_match_cannot_restart_or_publish_question(self):
        events = []
        engine = GameEngine(lambda *event: events.append(event))
        quiz = self.lobby._bank.quizzes[0]
        match = engine.create_match("stop", quiz.quiz_id, quiz.question_payloads(), {"a": "A", "b": "B"})
        engine.stop_match(match)
        self.assertEqual(engine.start_match(match)["error"]["code"], "SERVER_SHUTDOWN")
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()

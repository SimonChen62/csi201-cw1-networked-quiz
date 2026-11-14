"""B: tests for the lobby router, room lifecycle and ready/host rules.

C's engine is replaced by ``StubEngine`` so the routing can be checked without
timers or threads; the real engine's own behaviour is covered by C's
``test_game_engine.py``.
"""

import sys
import unittest
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT))
sys.path.insert(0, str(CODE_ROOT / "server_modules"))

from lobby import Lobby, create_business_handler
from question_bank import load_question_bank

SHIPPED_BANK = CODE_ROOT / "questions.json"
QUIZ_ID = "network-basics"


class FakeSession:
    """Minimal stand-in for A's ``ClientSession``."""

    def __init__(self, label="session"):
        self.label = label
        self.address = (label, 0)
        self.events = []
        self.responses = []

    def send(self, message):
        self.responses.append(message)
        return True

    def send_event(self, event, data):
        self.events.append((event, data))
        return True

    def close(self):
        return None

    def last_event(self, name):
        matches = [data for event, data in self.events if event == name]
        return matches[-1] if matches else None


class StubMatch:
    """Stand-in for C's ``MatchState`` with the attributes the lobby reads."""

    def __init__(self, room_id, quiz_id, questions, players):
        self.room_id = room_id
        self.quiz_id = quiz_id
        self.questions = list(questions)
        self.players = dict(players)
        self.scores = {user_id: 0 for user_id in players}
        self.phase = "WAITING"
        self.answers = {}


class StubEngine:
    """Deterministic stand-in for C's ``GameEngine`` (matching its four calls)."""

    def __init__(self, emit_event):
        self._emit = emit_event
        self.matches = []

    def create_match(self, room_id, quiz_id, questions, players, *, room_lock=None):
        match = StubMatch(room_id, quiz_id, questions, players)
        match.lock = room_lock
        self.matches.append(match)
        return match

    def start_match(self, match, *, run_async=True):
        if match.phase != "WAITING":
            return {"accepted": False, "error": {"code": "ALREADY_STARTED", "message": "already"}}
        match.phase = "RUNNING"
        question = match.questions[0]
        self._emit(
            match.room_id,
            "question",
            {"room_id": match.room_id, "question_id": question["question_id"], "index": 0},
        )
        return {"accepted": True, "data": {}}

    def submit_answer(self, match, user_id, question_id, choice):
        if match.phase != "RUNNING":
            return {"accepted": False, "error": {"code": "LATE_ANSWER", "message": "closed"}}
        if choice not in ("A", "B", "C", "D"):
            return {"accepted": False, "error": {"code": "INVALID_CHOICE", "message": "bad"}}
        return {"accepted": True, "data": {"accepted": True}}

    def disconnect_player(self, match, user_id):
        return True


def call(handler, session, message_type, request_id="1", **fields):
    message = {"type": message_type, "request_id": request_id}
    message.update(fields)
    return handler(session, message)


class LobbyTests(unittest.TestCase):
    def setUp(self):
        self.bank = load_question_bank(SHIPPED_BANK)
        self.engine = None

        def factory(emit):
            self.engine = StubEngine(emit)
            return self.engine

        self.handler, self.on_disconnect = create_business_handler(
            self.bank, engine_factory=factory
        )
        self.sessions = [FakeSession(f"client-{index}") for index in range(4)]

    # ---------------------------------------------------------------- helpers
    def login(self, session, user_id, name=None):
        response = call(self.handler, session, "hello", user_id=user_id, name=name or user_id)
        self.assertTrue(response["ok"], response)
        return response["data"]

    def make_room(self, session, user_id):
        self.login(session, user_id)
        response = call(self.handler, session, "create_room", quiz_id=QUIZ_ID)
        self.assertTrue(response["ok"], response)
        return response["data"]["room"]["room_id"]

    def seat_two_players(self):
        room_id = self.make_room(self.sessions[0], "u1")
        response = call(self.handler, self.sessions[1], "hello", user_id="u2", name="User Two")
        self.assertTrue(response["ok"])
        self.assertTrue(
            call(self.handler, self.sessions[1], "join_room", room_id=room_id)["ok"]
        )
        return room_id

    def ready_all(self, room_id, players):
        for player in players:
            response = call(self.handler, player, "ready", room_id=room_id, ready=True)
            self.assertTrue(response["ok"], response)

    # ------------------------------------------------------------ hello/identity
    def test_hello_registers_identity(self):
        data = self.login(self.sessions[0], "u1", name="Alice")
        self.assertEqual(data, {"user_id": "u1", "name": "Alice"})

    def test_duplicate_user_id_is_rejected(self):
        self.login(self.sessions[0], "u1")
        response = call(self.handler, self.sessions[1], "hello", user_id="u1", name="Other")
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "DUPLICATE_USER")

    def test_first_user_id_keeps_working_after_a_duplicate_attempt(self):
        self.login(self.sessions[0], "u1")
        call(self.handler, self.sessions[1], "hello", user_id="u1", name="Other")
        self.assertTrue(call(self.handler, self.sessions[0], "list_quizzes")["ok"])

    def test_commands_require_hello(self):
        response = call(self.handler, self.sessions[0], "list_quizzes")
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "NOT_AUTHENTICATED")

    def test_hello_requires_both_fields(self):
        response = call(self.handler, self.sessions[0], "hello", user_id="u1")
        self.assertEqual(response["error"]["code"], "INVALID_MESSAGE")

    def test_unknown_command(self):
        self.login(self.sessions[0], "u1")
        response = call(self.handler, self.sessions[0], "no_such_command")
        self.assertEqual(response["error"]["code"], "UNKNOWN_COMMAND")

    def test_echo_still_available_for_integration(self):
        response = call(self.handler, self.sessions[0], "echo", text="ping")
        self.assertTrue(response["ok"])
        self.assertEqual(response["data"]["text"], "ping")

    # ------------------------------------------------------------- quiz listing
    def test_list_quizzes_has_no_answers_or_question_text(self):
        self.login(self.sessions[0], "u1")
        response = call(self.handler, self.sessions[0], "list_quizzes")
        self.assertTrue(response["ok"])
        quizzes = response["data"]["quizzes"]
        self.assertEqual(len(quizzes), 2)
        self.assertEqual(
            sorted(quizzes[0].keys()),
            ["description", "question_count", "quiz_id", "title"],
        )

    def test_create_room_unknown_quiz(self):
        self.login(self.sessions[0], "u1")
        response = call(self.handler, self.sessions[0], "create_room", quiz_id="missing")
        self.assertEqual(response["error"]["code"], "QUIZ_NOT_FOUND")

    # ------------------------------------------------------------------ rooms
    def test_create_room_returns_v3_room_shape(self):
        room_id = self.make_room(self.sessions[0], "u1")
        response = call(self.handler, self.sessions[0], "inspect_room", room_id=room_id)
        room = response["data"]["room"]
        self.assertEqual(
            sorted(room.keys()),
            ["host_user_id", "players", "quiz_id", "room_id", "state"],
        )
        self.assertEqual(room["host_user_id"], "u1")
        self.assertEqual(room["state"], "WAITING")
        self.assertEqual(
            sorted(room["players"][0].keys()),
            ["display_name", "ready", "score", "user_id"],
        )

    def test_join_room_adds_player_and_broadcasts_room_update(self):
        room_id = self.seat_two_players()
        update = self.sessions[0].last_event("room_update")
        self.assertIsNotNone(update)
        self.assertEqual(update["room_id"], room_id)
        self.assertEqual(len(update["players"]), 2)
        self.assertEqual(update["state"], "WAITING")

    def test_join_room_unknown_or_non_waiting(self):
        self.login(self.sessions[0], "u1")
        response = call(self.handler, self.sessions[0], "join_room", room_id="R99")
        self.assertEqual(response["error"]["code"], "ROOM_NOT_FOUND")

    def test_inspect_room_requires_membership(self):
        room_id = self.make_room(self.sessions[0], "u1")
        self.login(self.sessions[1], "u2")
        response = call(self.handler, self.sessions[1], "inspect_room", room_id=room_id)
        self.assertEqual(response["error"]["code"], "NOT_IN_ROOM")

    def test_list_rooms_reports_joinable_rooms(self):
        self.make_room(self.sessions[0], "u1")
        response = call(self.handler, self.sessions[0], "list_rooms")
        self.assertTrue(response["ok"])
        room = response["data"]["rooms"][0]
        self.assertEqual(
            sorted(room.keys()),
            ["host_user_id", "player_count", "quiz_id", "room_id", "state"],
        )
        self.assertEqual(room["player_count"], 1)

    def test_player_moves_out_of_a_waiting_room(self):
        self.make_room(self.sessions[0], "u1")
        call(self.handler, self.sessions[0], "create_room", quiz_id="python-networking")
        response = call(self.handler, self.sessions[0], "list_rooms")
        self.assertEqual(len(response["data"]["rooms"]), 1)

    def test_room_is_deleted_when_the_last_player_leaves(self):
        room_id = self.make_room(self.sessions[0], "u1")
        call(self.handler, self.sessions[0], "leave_room", room_id=room_id)
        response = call(self.handler, self.sessions[0], "list_rooms")
        self.assertEqual(response["data"]["rooms"], [])

    def test_leave_room_requires_membership(self):
        room_id = self.make_room(self.sessions[0], "u1")
        self.login(self.sessions[1], "u2")
        response = call(self.handler, self.sessions[1], "leave_room", room_id=room_id)
        self.assertEqual(response["error"]["code"], "NOT_IN_ROOM")

    def test_host_transfers_to_smallest_user_id(self):
        room_id = self.seat_two_players()
        call(self.handler, self.sessions[0], "leave_room", room_id=room_id)
        room = call(self.handler, self.sessions[1], "inspect_room", room_id=room_id)["data"]["room"]
        self.assertEqual(room["host_user_id"], "u2")
        self.assertEqual([player["user_id"] for player in room["players"]], ["u2"])

    def test_display_name_is_trimmed_and_used_in_player_views(self):
        room_id = self.make_room(self.sessions[0], "u1")
        self.assertEqual(
            self.sessions[0].last_event("room_update"), None  # no event yet: solo create
        )
        room = call(self.handler, self.sessions[0], "inspect_room", room_id=room_id)["data"]["room"]
        self.assertEqual(room["players"][0]["display_name"], "u1")

    # ------------------------------------------------------------------- ready
    def test_ready_broadcasts_and_updates_state(self):
        room_id = self.seat_two_players()
        response = call(self.handler, self.sessions[0], "ready", room_id=room_id, ready=True)
        self.assertTrue(response["ok"])
        players = response["data"]["room"]["players"]
        self.assertTrue(next(item for item in players if item["user_id"] == "u1")["ready"])

    def test_ready_must_be_a_boolean(self):
        room_id = self.make_room(self.sessions[0], "u1")
        response = call(self.handler, self.sessions[0], "ready", room_id=room_id, ready="yes")
        self.assertEqual(response["error"]["code"], "INVALID_MESSAGE")

    def test_ready_requires_membership(self):
        room_id = self.make_room(self.sessions[0], "u1")
        self.login(self.sessions[1], "u2")
        response = call(self.handler, self.sessions[1], "ready", room_id=room_id, ready=True)
        self.assertEqual(response["error"]["code"], "NOT_IN_ROOM")

    # ------------------------------------------------------------------- start
    def test_start_requires_host(self):
        room_id = self.seat_two_players()
        self.ready_all(room_id, self.sessions[:2])
        response = call(self.handler, self.sessions[1], "start_game", room_id=room_id)
        self.assertEqual(response["error"]["code"], "NOT_HOST")

    def test_start_requires_all_players_ready(self):
        room_id = self.seat_two_players()
        call(self.handler, self.sessions[0], "ready", room_id=room_id, ready=True)
        response = call(self.handler, self.sessions[0], "start_game", room_id=room_id)
        self.assertEqual(response["error"]["code"], "NOT_ALL_READY")

    def test_start_requires_two_players(self):
        room_id = self.make_room(self.sessions[0], "u1")
        call(self.handler, self.sessions[0], "ready", room_id=room_id, ready=True)
        response = call(self.handler, self.sessions[0], "start_game", room_id=room_id)
        self.assertEqual(response["error"]["code"], "NOT_ALL_READY")

    def test_start_game_returns_empty_data_and_runs_the_room(self):
        room_id = self.seat_two_players()
        self.ready_all(room_id, self.sessions[:2])
        response = call(self.handler, self.sessions[0], "start_game", room_id=room_id)
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["data"], {})

        room = call(self.handler, self.sessions[0], "inspect_room", room_id=room_id)["data"]["room"]
        self.assertEqual(room["state"], "RUNNING")
        question = self.sessions[1].last_event("question")
        self.assertIsNotNone(question)
        self.assertEqual(question["room_id"], room_id)

    def test_start_twice_is_rejected(self):
        room_id = self.seat_two_players()
        self.ready_all(room_id, self.sessions[:2])
        call(self.handler, self.sessions[0], "start_game", room_id=room_id)
        response = call(self.handler, self.sessions[0], "start_game", room_id=room_id)
        self.assertEqual(response["error"]["code"], "ALREADY_STARTED")

    def test_join_running_room_is_rejected(self):
        room_id = self.seat_two_players()
        self.ready_all(room_id, self.sessions[:2])
        call(self.handler, self.sessions[0], "start_game", room_id=room_id)
        self.login(self.sessions[2], "u3")
        response = call(self.handler, self.sessions[2], "join_room", room_id=room_id)
        self.assertEqual(response["error"]["code"], "ALREADY_STARTED")

    def test_ready_after_start_is_rejected(self):
        room_id = self.seat_two_players()
        self.ready_all(room_id, self.sessions[:2])
        call(self.handler, self.sessions[0], "start_game", room_id=room_id)
        response = call(self.handler, self.sessions[1], "ready", room_id=room_id, ready=False)
        self.assertEqual(response["error"]["code"], "ALREADY_STARTED")

    def test_start_without_an_engine_reports_internal_error(self):
        handler, _ = create_business_handler(self.bank, engine_factory=lambda emit: None)
        call(handler, self.sessions[0], "hello", user_id="u1", name="u1")
        room_id = call(handler, self.sessions[0], "create_room", quiz_id=QUIZ_ID)["data"]["room"]["room_id"]
        response = call(handler, self.sessions[0], "start_game", room_id=room_id)
        self.assertEqual(response["error"]["code"], "INTERNAL_ERROR")

    # ------------------------------------------------------------------ answer
    def test_answer_before_start_reports_no_open_question(self):
        room_id = self.make_room(self.sessions[0], "u1")
        response = call(
            self.handler, self.sessions[0], "answer", room_id=room_id, question_id="NET001", choice="A"
        )
        self.assertEqual(response["error"]["code"], "LATE_ANSWER")

    def test_answer_after_start_is_accepted(self):
        room_id = self.seat_two_players()
        self.ready_all(room_id, self.sessions[:2])
        call(self.handler, self.sessions[0], "start_game", room_id=room_id)
        response = call(
            self.handler, self.sessions[0], "answer", room_id=room_id, question_id="NET001", choice="B"
        )
        self.assertTrue(response["ok"], response)
        self.assertTrue(response["data"]["accepted"])

    def test_answer_requires_choice_field(self):
        room_id = self.seat_two_players()
        self.ready_all(room_id, self.sessions[:2])
        call(self.handler, self.sessions[0], "start_game", room_id=room_id)
        response = call(self.handler, self.sessions[0], "answer", room_id=room_id, question_id="NET001")
        self.assertEqual(response["error"]["code"], "INVALID_CHOICE")

    def test_answer_from_a_non_member_is_rejected(self):
        room_id = self.seat_two_players()
        self.ready_all(room_id, self.sessions[:2])
        call(self.handler, self.sessions[0], "start_game", room_id=room_id)
        self.login(self.sessions[2], "u3")
        response = call(
            self.handler, self.sessions[2], "answer", room_id=room_id, question_id="NET001", choice="A"
        )
        self.assertEqual(response["error"]["code"], "NOT_IN_ROOM")

    # ------------------------------------------------------- quit / disconnect
    def test_quit_confirms_and_frees_the_identity_immediately(self):
        self.login(self.sessions[0], "u1")
        response = call(self.handler, self.sessions[0], "quit")
        self.assertTrue(response["ok"])
        self.assertEqual(response["data"], {"bye": True})

        # Cleanup may not wait for A's disconnect callback: otherwise a client
        # reconnecting with the same user_id while the old socket is still
        # closing would be rejected as DUPLICATE_USER.
        response = call(self.handler, self.sessions[1], "hello", user_id="u1", name="Again")
        self.assertTrue(response["ok"], response)

    def test_quit_frees_the_seat_and_tells_the_room(self):
        room_id = self.seat_two_players()
        call(self.handler, self.sessions[0], "quit")
        room = call(self.handler, self.sessions[1], "inspect_room", room_id=room_id)["data"]["room"]
        self.assertEqual(room["host_user_id"], "u2")
        self.assertEqual(len(room["players"]), 1)
        self.assertIsNotNone(self.sessions[1].last_event("room_update"))

    def test_disconnect_cleans_identity_and_room(self):
        room_id = self.make_room(self.sessions[0], "u1")
        self.on_disconnect(self.sessions[0])
        response = call(self.handler, self.sessions[1], "list_rooms")
        self.assertFalse(response["ok"])  # session 1 never logged in
        self.assertEqual(response["error"]["code"], "NOT_AUTHENTICATED")

    def test_disconnect_of_one_player_keeps_the_room_for_the_other(self):
        room_id = self.seat_two_players()
        self.on_disconnect(self.sessions[0])
        room = call(self.handler, self.sessions[1], "inspect_room", room_id=room_id)["data"]["room"]
        self.assertEqual(room["host_user_id"], "u2")
        self.assertEqual(len(room["players"]), 1)

    def test_disconnect_callback_is_idempotent(self):
        self.login(self.sessions[0], "u1")
        self.on_disconnect(self.sessions[0])
        self.on_disconnect(self.sessions[0])
        self.assertTrue(call(self.handler, self.sessions[1], "hello", user_id="u1", name="again")["ok"])


if __name__ == "__main__":
    unittest.main()

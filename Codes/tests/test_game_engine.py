"""Unit tests for C's room-isolated timed game engine."""

import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server_modules"))

from game_engine import FINISHED, GameEngine


QUESTIONS = [
    {
        "question_id": "Q1",
        "text": "First question",
        "options": {"A": "alpha", "B": "beta"},
        "answer": "A",
        "time_limit": 10,
        "points": 100,
    },
    {
        "question_id": "Q2",
        "text": "Second question",
        "options": {"A": "alpha", "B": "beta"},
        "answer": "B",
        "time_limit": 10,
        "points": 50,
    },
]


class MutableClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class GameEngineTests(unittest.TestCase):
    def setUp(self):
        self.clock = MutableClock()
        self.events = []
        self.engine = GameEngine(
            lambda room_id, event, data: self.events.append((room_id, event, data)),
            clock=self.clock,
        )
        self.players = {
            "alice": {"display_name": "Alice"},
            "bob": {"display_name": "Bob"},
        }

    def make_match(self, room_id="room-1"):
        return self.engine.create_match(room_id, "quiz-1", QUESTIONS, self.players)

    def start(self, match):
        response = self.engine.start_match(match, run_async=False)
        self.assertTrue(response["accepted"])
        return response

    def test_question_event_hides_answer_and_scores_correct_answers(self):
        match = self.make_match()
        self.start(match)
        room_id, event, question = self.events[-1]
        self.assertEqual((room_id, event), ("room-1", "question_open"))
        self.assertEqual(
            self.events[-2],
            ("room-1", "game_started", {"room_id": "room-1", "quiz_id": "quiz-1", "question_count": 2}),
        )
        self.assertNotIn("answer", question)
        self.assertNotIn("correct", question)
        self.assertEqual(question["index"], 0)

        self.assertTrue(self.engine.submit_answer(match, "alice", "Q1", "A")["accepted"])
        self.assertTrue(self.engine.submit_answer(match, "bob", "Q1", "B")["accepted"])
        self.assertTrue(self.engine.close_current_question(match))

        _, event, result = self.events[-2]
        self.assertEqual(event, "question_closed")
        self.assertEqual(result["correct"], "A")
        self.assertEqual(result["scores"], {"alice": 100, "bob": 0})
        self.assertEqual(self.events[-1][1], "question_open")

    def test_duplicate_and_late_answers_are_rejected_without_score_change(self):
        match = self.make_match()
        self.start(match)
        invalid_choice = self.engine.submit_answer(match, "alice", "Q1", "Z")
        self.assertEqual(invalid_choice["error"]["code"], "INVALID_CHOICE")
        self.assertTrue(self.engine.submit_answer(match, "alice", "Q1", "A")["accepted"])

        duplicate = self.engine.submit_answer(match, "alice", "Q1", "B")
        self.assertEqual(duplicate["error"]["code"], "DUPLICATE_ANSWER")

        self.clock.now += 10
        late = self.engine.submit_answer(match, "bob", "Q1", "A")
        self.assertEqual(late["error"]["code"], "LATE_ANSWER")
        self.assertTrue(self.engine.close_current_question(match))
        self.assertEqual(self.events[-2][2]["scores"], {"alice": 100, "bob": 0})

    def test_scores_and_events_do_not_leak_between_rooms(self):
        room_one = self.make_match("room-one")
        room_two = self.make_match("room-two")
        self.start(room_one)
        self.start(room_two)

        self.assertTrue(self.engine.submit_answer(room_one, "alice", "Q1", "A")["accepted"])
        self.assertTrue(self.engine.submit_answer(room_one, "bob", "Q1", "B")["accepted"])
        self.assertTrue(self.engine.close_current_question(room_one))

        self.assertEqual(self.engine.snapshot(room_one)["scores"], {"alice": 100, "bob": 0})
        self.assertEqual(self.engine.snapshot(room_two)["scores"], {"alice": 0, "bob": 0})
        room_two_events = [event for room_id, event, _ in self.events if room_id == "room-two"]
        self.assertEqual(room_two_events, ["game_started", "question_open"])

    def test_final_leaderboard_is_stable_and_includes_disconnected_player(self):
        match = self.make_match()
        self.start(match)
        self.assertTrue(self.engine.submit_answer(match, "alice", "Q1", "A")["accepted"])
        self.assertTrue(self.engine.disconnect_player(match, "bob"))
        self.clock.now += 10
        self.assertTrue(self.engine.close_current_question(match))

        self.assertTrue(self.engine.submit_answer(match, "alice", "Q2", "B")["accepted"])
        self.clock.now += 10
        self.assertTrue(self.engine.close_current_question(match))
        self.assertEqual(match.phase, FINISHED)

        _, event, data = self.events[-1]
        self.assertEqual(event, "game_finished")
        self.assertEqual(
            data["leaderboard"],
            [
                {"rank": 1, "user_id": "alice", "display_name": "Alice", "score": 150},
                {"rank": 2, "user_id": "bob", "display_name": "Bob", "score": 0},
            ],
        )

    def test_start_requires_two_players_by_default(self):
        match = self.engine.create_match(
            "solo", "quiz-1", QUESTIONS, {"alice": {"display_name": "Alice"}}
        )
        response = self.engine.start_match(match, run_async=False)
        self.assertFalse(response["accepted"])
        self.assertEqual(response["error"]["code"], "NOT_ALL_READY")
        self.assertFalse(self.events)

    def test_timer_thread_closes_question_at_server_deadline(self):
        finished = threading.Event()
        events = []

        def record_event(room_id, event, data):
            events.append((room_id, event, data))
            if event == "game_finished":
                finished.set()

        timed_question = [dict(QUESTIONS[0], time_limit=0.02)]
        engine = GameEngine(record_event)
        match = engine.create_match("timed", "quiz-1", timed_question, self.players)
        self.assertTrue(engine.start_match(match)["accepted"])
        self.assertTrue(finished.wait(0.5), "timer worker did not finish the question")
        self.assertEqual(match.phase, FINISHED)
        self.assertEqual(
            [event for _, event, _ in events],
            ["game_started", "question_open", "question_closed", "game_finished"],
        )

    def test_ten_players_can_progress_in_two_independent_rooms(self):
        players = {
            f"player-{number}": {"display_name": f"Player {number}"}
            for number in range(10)
        }
        room_one = self.engine.create_match("room-one", "quiz-1", QUESTIONS, dict(list(players.items())[:5]))
        room_two = self.engine.create_match("room-two", "quiz-1", QUESTIONS, dict(list(players.items())[5:]))
        self.start(room_one)
        self.start(room_two)

        for user_id in room_one.scores:
            self.assertTrue(self.engine.submit_answer(room_one, user_id, "Q1", "A")["accepted"])
        for user_id in room_two.scores:
            self.assertTrue(self.engine.submit_answer(room_two, user_id, "Q1", "B")["accepted"])

        self.assertTrue(self.engine.close_current_question(room_one))
        self.assertTrue(self.engine.close_current_question(room_two))
        self.assertTrue(all(score == 100 for score in room_one.scores.values()))
        self.assertTrue(all(score == 0 for score in room_two.scores.values()))


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client_modules"))

from state import ClientState, PlayerInfo, QuestionInfo


class TestClientState(unittest.TestCase):
    def setUp(self):
        self.state = ClientState()
        self.state.set_connected("u1", "Alice")

    def test_01_connection_state(self):
        """Test connection and disconnection state"""
        self.assertTrue(self.state.connected)
        self.assertEqual(self.state.user_id, "u1")
        
        # Disconnecting should clear all state
        self.state.set_disconnected()
        self.assertFalse(self.state.connected)
        self.assertIsNone(self.state.current_room_id)

    def test_02_enter_and_leave_room(self):
        """Test entering and leaving a room, as well as host determination"""
        players = [
            {"user_id": "u1", "name": "Alice", "ready": True},
            {"user_id": "u2", "name": "Bob", "ready": False}
        ]
        self.state.enter_room("room-A", host_id="u1", players=players)
        
        self.assertEqual(self.state.current_room_id, "room-A")
        self.assertTrue(self.state.is_host)  # u1 is the host
        self.assertEqual(len(self.state.players_in_room), 2)
        self.assertTrue(self.state.players_in_room["u1"].ready)
        
        # Leaving the room should clean up completely
        self.state.leave_room()
        self.assertIsNone(self.state.current_room_id)
        self.assertFalse(self.state.is_host)
        self.assertEqual(len(self.state.players_in_room), 0)

    def test_03_update_players_keep_score(self):
        """Test that old scores are not accidentally reset when updating the player list"""
        self.state.enter_room("room-A", "u1", [{"user_id": "u1", "name": "Alice", "score": 100}])
        self.assertEqual(self.state.players_in_room["u1"].score, 100)
        
        # The server sends a new update without the score field
        self.state.update_room_players([{"user_id": "u1", "name": "Alice", "ready": True}])
        # The score should be preserved, and the ready state should be updated
        self.assertEqual(self.state.players_in_room["u1"].score, 100)
        self.assertTrue(self.state.players_in_room["u1"].ready)

    def test_04_question_flow_and_duplicate_prevention(self):
        """Test the flow of sending a question, answering, and revealing the answer"""
        # [Modification] First add the player to the room to ensure the game starts inside the room
        self.state.enter_room("room-1", "u1", [{"user_id": "u1", "name": "Alice"}])
        
        self.state.start_game()
        self.assertEqual(self.state.room_phase, "RUNNING")
        
        # 1. Receive the question (even if the server mistakenly includes answer, it should be ignored)
        q_data = {
            "question_id": "q1",
            "text": "What is TCP?",
            "options": {"A": "UDP", "B": "Stream"},
            "time_limit": 15,
            "points": 100,
            "answer": "B"  # Intentionally pass the answer to verify whether state ignores it
        }
        self.state.set_question(q_data)
        
        self.assertIsNotNone(self.state.current_question)
        self.assertFalse(hasattr(self.state.current_question, "answer")) # Confirm the answer was not saved
        self.assertFalse(self.state.has_answered_current_question)
        
        # 2. Submit the answer and mark it as answered
        self.state.mark_answered()
        self.assertTrue(self.state.has_answered_current_question)
        
        # 3. The question ends and the result is received
        result_data = {
            "question_id": "q1",
            "answer": "B",
            "scores": {"u1": 100}
        }
        self.state.set_question_result(result_data)
        
        self.assertIsNone(self.state.current_question) # The question is closed
        self.assertIsNotNone(self.state.last_result)
        self.assertEqual(self.state.last_result.correct_answer, "B")
        
        # Verify the score update succeeded
        self.assertEqual(self.state.players_in_room["u1"].score, 100)

    def test_05_state_isolation(self):
        """Test that match data does not leak between rooms when switching rooms"""
        # Played halfway in Room A
        self.state.enter_room("room-A", "u1", [])
        self.state.start_game()
        self.state.set_question({"question_id": "q1", "text": "Q1", "options": {}})
        
        # Leave Room A and enter Room B
        self.state.leave_room()
        self.state.enter_room("room-B", "u1", [])
        
        # Verify that Room A's question data was not carried over
        self.assertIsNone(self.state.current_question)
        self.assertIsNone(self.state.last_result)
        self.assertEqual(self.state.room_phase, "WAITING")

    def test_06_thread_safe_snapshot(self):
        """Test snapshot deep copy, and that high-concurrency reads do not crash"""
        self.state.enter_room("room-A", "u1", [{"user_id": "u1", "name": "Alice"}])
        
        # 1. Test deep copy isolation
        snap1 = self.state.get_snapshot()
        snap1["players"]["u1"]["score"] = 9999  # Tamper with the snapshot
        snap2 = self.state.get_snapshot()
        self.assertEqual(snap2["players"]["u1"]["score"], 0) # Internal state was not tampered with

        # 2. Multithreaded concurrent read/write test
        def modify_state():
            for i in range(100):
                self.state.update_room_players([
                    {"user_id": f"u{i}", "name": f"P{i}"}
                ])
                time.sleep(0.001)

        def read_state():
            for _ in range(100):
                snap = self.state.get_snapshot()
                # Simulate the UI iterating over the dictionary
                for uid, p in snap["players"].items():
                    pass
        
        t1 = threading.Thread(target=modify_state)
        t2 = threading.Thread(target=read_state)
        t1.start(); t2.start()
        t1.join(); t2.join()
        # If no RuntimeError: dictionary changed size during iteration is raised, the snapshot mechanism works


if __name__ == "__main__":
    unittest.main()

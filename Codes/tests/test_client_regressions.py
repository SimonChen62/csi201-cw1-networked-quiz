"""Regression checks for the D/E hand-off found during E integration."""

from pathlib import Path
import queue
import socket
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from client_modules.connection import Connection
from client_modules.state import ClientState
from client_modules.cli import parse_command
from protocol import encode_message, decode_message, ProtocolError


def question(qid="q1", room_id="r1"):
    return {"room_id": room_id, "question_id": qid, "text": "Question",
            "options": {"A": "a", "B": "b", "C": "c", "D": "d"}, "time_limit": 5, "points": 100}


class ScriptedSocket:
    def __init__(self, replies):
        self.replies = replies
        self.incoming = queue.Queue()
        self.sent = []

    def sendall(self, payload):
        request = decode_message(payload.rstrip(b"\n"))
        self.sent.append(request)
        for reply in self.replies(request):
            self.incoming.put(encode_message(reply))

    def recv(self, size):
        try:
            return self.incoming.get(timeout=0.02)
        except queue.Empty:
            raise socket.timeout()

    def shutdown(self, how):
        pass

    def close(self):
        pass


class ClientIntegrationRegressionTest(unittest.TestCase):
    def make_connection(self, replies):
        state = ClientState()
        state.set_connected("u1", "Alice")
        state.enter_room("r1", "u1", [{"user_id": "u1", "name": "Alice"}])
        connection = Connection(state)
        connection.sock = ScriptedSocket(replies)
        connection.is_running = True
        connection._reader = threading.Thread(target=connection._receive_loop, daemon=True)
        connection._reader.start()
        self.addCleanup(connection.disconnect)
        return connection, state

    def test_server_error_is_returned_and_pending_request_is_removed(self):
        connection, _ = self.make_connection(lambda request: [{
            "type": "response", "request_id": request["request_id"], "ok": False,
            "error": {"code": "ROOM_NOT_FOUND", "message": "Missing room"},
        }])
        response = connection.send_request("join_room", {"room_id": "missing"}, timeout=0.5)
        self.assertEqual(response["error"]["code"], "ROOM_NOT_FOUND")
        self.assertFalse(response["ok"])
        self.assertFalse(connection.pending_requests)

    def test_completed_requests_do_not_accumulate(self):
        connection, _ = self.make_connection(lambda request: [{
            "type": "response", "request_id": request["request_id"], "ok": True, "data": {},
        }])
        for _ in range(10):
            self.assertTrue(connection.send_request("ping", {}, timeout=0.5)["ok"])
        self.assertFalse(connection.pending_requests)

    def test_timeout_is_unknown_and_does_not_retry(self):
        connection, _ = self.make_connection(lambda request: [])
        response = connection.send_request("start_game", {"room_id": "r1"}, timeout=0.05)
        self.assertEqual(response["error"]["code"], "TIMEOUT")
        self.assertIn("unknown", response["error"]["message"])
        self.assertEqual(len(connection.sock.sent), 1)
        self.assertFalse(connection.pending_requests)

    def test_late_answer_ack_does_not_mark_the_next_question(self):
        connection, state = self.make_connection(lambda request: [
            {"type": "event", "event": "question", "data": question("q2")},
            {"type": "response", "request_id": request["request_id"], "ok": True,
             "data": {"accepted": True}},
        ])
        state.set_question(question("q1"))
        connection.send_request("answer", {"room_id": "r1", "question_id": "q1", "choice": "B"})
        snapshot = state.get_snapshot()
        self.assertEqual(snapshot["current_question"]["id"], "q2")
        self.assertFalse(snapshot["has_answered"])

    def test_state_is_updated_before_ui_event_and_foreign_room_is_ignored(self):
        connection, state = self.make_connection(lambda request: [])
        connection.sock.incoming.put(encode_message({"type": "event", "event": "question", "data": question()}))
        message = connection.event_queue.get(timeout=1)
        self.assertEqual(message["event"], "question")
        self.assertEqual(state.get_snapshot()["room_phase"], "RUNNING")
        self.assertFalse(connection._handle_event_state_update({
            "type": "event", "event": "question", "data": question("foreign", "another-room"),
        }))
        self.assertEqual(state.get_snapshot()["current_question"]["id"], "q1")

    def test_error_does_not_undo_an_accepted_answer(self):
        connection, state = self.make_connection(lambda request: [{
            "type": "response", "request_id": request["request_id"], "ok": False,
            "error": {"code": "DUPLICATE_ANSWER", "message": "Already answered"},
        }])
        state.set_question(question())
        state.mark_answered("q1", "r1")
        connection.send_request("answer", {"room_id": "r1", "question_id": "q1", "choice": "A"})
        self.assertTrue(state.get_snapshot()["has_answered"])

    def test_incomplete_question_event_is_rejected_before_reaching_ui(self):
        connection, _ = self.make_connection(lambda request: [])
        with self.assertRaises(ProtocolError):
            connection._handle_event_state_update({
                "type": "event", "event": "question", "data": {"room_id": "r1"},
            })


class ClientStateBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.state = ClientState()
        self.state.set_connected("u1", "Alice")
        self.state.enter_room("r1", "u1", [{"user_id": "u1", "name": "Alice"}])

    def test_catalogue_and_leaderboard_snapshots_are_detached(self):
        self.state.update_quizzes([{"quiz_id": "quiz1", "meta": {"count": 5}}])
        self.state.finish_game([{"user_id": "u1", "score": 100}])
        snapshot = self.state.get_snapshot()
        snapshot["leaderboard"][0]["score"] = 999
        snapshot["available_quizzes"][0]["meta"]["count"] = 99
        self.assertEqual(self.state.get_snapshot()["leaderboard"][0]["score"], 100)
        self.assertEqual(self.state.get_snapshot()["available_quizzes"][0]["meta"]["count"], 5)

    def test_old_result_cannot_close_current_question(self):
        self.state.set_question(question("q2"))
        self.assertFalse(self.state.set_question_result({
            "room_id": "r1", "question_id": "q1", "answer": "B", "scores": {"u1": 100},
        }))
        self.assertEqual(self.state.get_snapshot()["current_question"]["id"], "q2")

    def test_host_transfer_updates_permission_view(self):
        self.state.update_room({"room_id": "r1", "host_user_id": "u2", "state": "WAITING"})
        self.assertFalse(self.state.get_snapshot()["is_host"])

    def test_answer_command_binds_explicit_question_id(self):
        self.state.set_question(question("q2"))
        with self.assertRaises(ValueError):
            parse_command("answer q1 B", self.state.get_snapshot())
        with self.assertRaises(ValueError):
            parse_command("answer B", self.state.get_snapshot())
        command, data = parse_command("answer q2 b", self.state.get_snapshot())
        self.assertEqual(command, "answer")
        self.assertEqual(data, {"room_id": "r1", "question_id": "q2", "choice": "B"})


if __name__ == "__main__":
    unittest.main()

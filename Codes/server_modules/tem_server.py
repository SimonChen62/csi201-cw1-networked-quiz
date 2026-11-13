"""D's complete temporary integration server for UI testing."""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server_modules"))

from server import Server, failure_response
from game_engine import GameEngine

FAKE_QUIZ = {
    "quiz_id": "demo-quiz",
    "title": "Integration Quiz",
    "questions": [
        {
            "question_id": "Q1", "text": "What is TCP?", "options": {"A": "UDP", "B": "Stream"},
            "answer": "B", "time_limit": 5, "points": 100
        }
    ]
}

sessions_to_user = {}
active_matches = {}
match_lock = threading.Lock()

def emit_event(room_id, event, data):
    with match_lock:
        if room_id not in active_matches:
            return
        match = active_matches[room_id]
        targets = [s for s, uid in sessions_to_user.items() if uid in match.player_names]

    if event == "question_open":
        event = "question"
    elif event == "question_closed":
        event = "question_result"
        if "correct" in data:
            data["answer"] = data.pop("correct")
    elif event == "game_finished":
        event = "leaderboard"

    server.broadcast_event(targets, event, data)

engine = GameEngine(emit_event, min_players=1)

def temp_router(session, message):
    req_id = message.get("request_id")
    req_type = message.get("type")
    room_id_in = message.get("room_id")

    if req_type == "hello":
        sessions_to_user[session] = message.get("user_id")
        return {"type": "response", "request_id": req_id, "ok": True, "data": {}}

    user_id = sessions_to_user.get(session)
    if not user_id:
        return failure_response(req_id, "NO_USER", "You must send hello first")

    # --- 补全 UI 里的所有查询命令 ---
    if req_type == "list_quizzes":
        return {"type": "response", "request_id": req_id, "ok": True, "data": {"quizzes": [{"quiz_id": "demo-quiz", "title": "Demo", "question_count": 1}]}}
    
    if req_type == "list_rooms":
        return {"type": "response", "request_id": req_id, "ok": True, "data": {"rooms": [{"room_id": "ROOM-1", "quiz_id": "demo-quiz", "state": "WAITING"}]}}
    
    # --- 房间操作 ---
    if req_type == "create_room":
        room_id = "ROOM-1"
        room_data = {
            "room_id": room_id, "quiz_id": "demo-quiz", "host_user_id": user_id, "state": "WAITING",
            "players": [{"user_id": user_id, "name": user_id, "ready": False, "score": 0}]
        }
        match = engine.create_match(room_id=room_id, quiz_id="demo-quiz", questions=FAKE_QUIZ["questions"], players={user_id: user_id})
        with match_lock:
            active_matches[room_id] = match
        return {"type": "response", "request_id": req_id, "ok": True, "data": {"room": room_data}}

    if req_type == "join_room":
        return {"type": "response", "request_id": req_id, "ok": True, "data": {"room": {"room_id": room_id_in, "quiz_id": "demo-quiz", "host_user_id": "u1", "state": "WAITING", "players": [{"user_id": user_id, "name": user_id, "ready": False, "score": 0}]}}}

    if req_type == "inspect_room" or req_type == "ready":
        return {"type": "response", "request_id": req_id, "ok": True, "data": {"room": {"room_id": room_id_in, "quiz_id": "demo-quiz", "host_user_id": user_id, "state": "WAITING", "players": [{"user_id": user_id, "name": user_id, "ready": True, "score": 0}]}}}

    # --- 开始游戏与答题 ---
    if req_type == "start_game":
        with match_lock:
            match = active_matches.get(room_id_in)
        if match:
            result = engine.start_match(match)
            if result.get("accepted"):
                return {"type": "response", "request_id": req_id, "ok": True, "data": {}}
            return failure_response(req_id, result["error"]["code"], result["error"]["message"])
        return failure_response(req_id, "NO_ROOM", "Room not found")

    if req_type == "answer":
        q_id = message.get("question_id")
        choice = message.get("answer")
        with match_lock:
            match = active_matches.get(room_id_in)
        if match:
            result = engine.submit_answer(match, user_id, q_id, choice)
            if result.get("accepted"):
                return {"type": "response", "request_id": req_id, "ok": True, "data": {"accepted": True}}
            return failure_response(req_id, result["error"]["code"], result["error"]["message"])
    
    return failure_response(req_id, "UNKNOWN", "Command not implemented")

def temp_on_disconnect(session):
    with match_lock:
        user_id = sessions_to_user.pop(session, None)
        for match in active_matches.values():
            if user_id in match.connected_players:
                engine.disconnect_player(match, user_id)

if __name__ == "__main__":
    server = Server("127.0.0.1", 5000, request_handler=temp_router, on_disconnect=temp_on_disconnect)
    print("SERVER_READY 127.0.0.1 5000 (COMPLETE TEMP ROUTER)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()

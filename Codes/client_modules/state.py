"""Member D: Local client state and thread-safe data management."""

import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class PlayerInfo:
    """Represents a player in the current room. NO password or sensitive data here."""
    user_id: str
    name: str
    ready: bool = False
    score: int = 0


@dataclass
class QuestionInfo:
    """Represents an ACTIVE question. 
    SECURITY: Must NOT contain the 'answer' field. Answer is only revealed after closure.
    """
    question_id: str
    text: str
    options: Dict[str, str]  # e.g., {"A": "TCP", "B": "UDP", "C": "ARP", "D": "ICMP"}
    time_limit: int
    points: int
    question_index: int = 0  # The order (0-based or 1-based) of the question


@dataclass
class QuestionResult:
    """Stores the result of a closed question."""
    question_id: str
    correct_answer: str
    scores: Dict[str, int]  # Updated total scores for all players


class ClientState:
    """
    Thread-safe storage for the client's local application state.
    Network thread (recv) modifies it; UI thread (input/print) reads it.
    """

    def __init__(self):
        self._lock = threading.RLock()

        # --- Connection & Identity ---
        self.connected: bool = False
        self.user_id: Optional[str] = None
        self.display_name: Optional[str] = None

        # --- Lobby State ---
        self.available_quizzes: List[Dict[str, Any]] = []
        self.available_rooms: List[Dict[str, Any]] = []

        # --- Room State (Isolated per room) ---
        self.current_room_id: Optional[str] = None
        self.is_host: bool = False
        self.room_phase: str = "LOBBY"  # LOBBY, WAITING, RUNNING, FINISHED
        self.players_in_room: Dict[str, PlayerInfo] = {}

        # --- Active Game State ---
        self.current_question: Optional[QuestionInfo] = None
        self.has_answered_current_question: bool = False  # Prevents duplicate answers at UI level
        self.last_result: Optional[QuestionResult] = None  # Shows answer AFTER question closes

        # --- Final State ---
        self.final_leaderboard: List[Dict[str, Any]] = []

    # ==========================================
    # Connection State Updates
    # ==========================================
    def set_connected(self, user_id: str, name: str):
        with self._lock:
            self.connected = True
            self.user_id = user_id
            self.display_name = name

    def set_disconnected(self):
        """Called when server drops or user quits. Resets everything."""
        with self._lock:
            self.connected = False
            self.user_id = None
            self.display_name = None
            self.leave_room()

    # ==========================================
    # Lobby State Updates
    # ==========================================
    def update_quizzes(self, quizzes: List[Dict[str, Any]]):
        with self._lock:
            self.available_quizzes = quizzes

    def update_rooms(self, rooms: List[Dict[str, Any]]):
        with self._lock:
            self.available_rooms = rooms

    # ==========================================
    # Room State Updates
    # ==========================================
    def enter_room(self, room_id: str, host_id: str, players: List[Dict[str, Any]]):
        with self._lock:
            # Clear previous room match data before entering a new room
            self._reset_game_state_internal()
            
            self.current_room_id = room_id
            self.is_host = (self.user_id == host_id)
            self.room_phase = "WAITING"
            self._update_players_internal(players)

    def leave_room(self):
        """Called when user leaves, gets kicked, or disconnects."""
        with self._lock:
            self.current_room_id = None
            self.is_host = False
            self.room_phase = "LOBBY"
            self.players_in_room.clear()
            self._reset_game_state_internal()

    def update_room_players(self, players: List[Dict[str, Any]]):
        with self._lock:
            self._update_players_internal(players)

    def _update_players_internal(self, players_data: List[Dict[str, Any]]):
        """Helper: Updates player list safely without losing existing scores."""
        new_players = {}
        for p in players_data:
            uid = p.get("user_id")
            if uid:
                # Retain score if server didn't send it in this update
                old_score = self.players_in_room[uid].score if uid in self.players_in_room else 0
                new_players[uid] = PlayerInfo(
                    user_id=uid,
                    name=p.get("name", "Unknown"),
                    ready=p.get("ready", False),
                    score=p.get("score", old_score)
                )
        self.players_in_room = new_players

    # ==========================================
    # Game State Updates
    # ==========================================
    def start_game(self):
        with self._lock:
            self.room_phase = "RUNNING"
            self._reset_game_state_internal()

    def set_question(self, q_data: Dict[str, Any]):
        """
        Called when server sends a 'question' event.
        """
        with self._lock:
            # SECURITY: Strictly parse only approved fields. Ignore 'answer' even if accidentally sent.
            self.current_question = QuestionInfo(
                question_id=q_data.get("question_id", ""),
                text=q_data.get("text", ""),
                options=q_data.get("options", {}),
                time_limit=q_data.get("time_limit", 15),
                points=q_data.get("points", 100),
                question_index=q_data.get("question_index", 0)
            )
            # New question arrived, allow user to answer
            self.has_answered_current_question = False
            self.last_result = None

    def mark_answered(self):
        """
        Called by UI (E) immediately after sending an answer.
        Blocks duplicate submissions at the client level.
        """
        with self._lock:
            self.has_answered_current_question = True

    def set_question_result(self, result_data: Dict[str, Any]):
        """
        Called when server sends 'question_result'.
        NOW we can accept and display the correct answer.
        """
        with self._lock:
            q_id = result_data.get("question_id", "")
            ans = result_data.get("answer", "")
            scores = result_data.get("scores", {})
            
            # Record the result (for UI to display)
            self.last_result = QuestionResult(
                question_id=q_id,
                correct_answer=ans,
                scores=scores
            )
            
            # Update scores in player list
            for uid, new_score in scores.items():
                if uid in self.players_in_room:
                    self.players_in_room[uid].score = new_score
            
            # Question is closed, clear active question
            self.current_question = None
            self.has_answered_current_question = False

    def finish_game(self, leaderboard: List[Dict[str, Any]]):
        with self._lock:
            self.room_phase = "FINISHED"
            self.current_question = None
            self.final_leaderboard = leaderboard

    def _reset_game_state_internal(self):
        """Helper: Clears game-specific data for isolation."""
        self.current_question = None
        self.has_answered_current_question = False
        self.last_result = None
        self.final_leaderboard.clear()

    # ==========================================
    # Thread-Safe Read Accessors
    # ==========================================
    def get_snapshot(self) -> Dict[str, Any]:
        """
        Returns a completely safe, detached copy of the state.
        UI MUST use this to avoid multi-threading race conditions.
        """
        with self._lock:
            # Make a deep copy of core data to avoid network thread modifications while iterating
            players_copy = {
                uid: {"name": p.name, "ready": p.ready, "score": p.score}
                for uid, p in self.players_in_room.items()
            }
            
            q_copy = None
            if self.current_question:
                q_copy = {
                    "id": self.current_question.question_id,
                    "index": self.current_question.question_index,
                    "text": self.current_question.text,
                    "options": dict(self.current_question.options), # Copy dict
                    "time_limit": self.current_question.time_limit,
                    "points": self.current_question.points
                }
                
            result_copy = None
            if self.last_result:
                result_copy = {
                    "correct_answer": self.last_result.correct_answer,
                    "scores": dict(self.last_result.scores)
                }

            return {
                "connected": self.connected,
                "user_id": self.user_id,
                "current_room_id": self.current_room_id,
                "is_host": self.is_host,
                "room_phase": self.room_phase,
                "players": players_copy,
                "current_question": q_copy,
                "has_answered": self.has_answered_current_question,
                "last_result": result_copy,
                "leaderboard": list(self.final_leaderboard)
            }

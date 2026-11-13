"""Thread-safe quiz match engine owned by team member C.

The engine owns only a room's match lifecycle. Lobby/user code validates the
host and ready-state rules, then creates a ``MatchState`` and supplies an
``emit_event`` callback which broadcasts frozen-v2 events to that room's
sessions. Each state has its own room lock, timer thread and score state.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
import threading
import time
from typing import Any

try:  # Supports both ``server_modules.game_engine`` and direct script-style imports.
    from .scoring import build_leaderboard
except ImportError:  # pragma: no cover - used by the existing test path.
    from scoring import build_leaderboard


WAITING = "WAITING"
RUNNING = "RUNNING"
FINISHED = "FINISHED"

EventEmitter = Callable[[str, str, dict[str, Any]], None]
Clock = Callable[[], float]


@dataclass
class MatchState:
    """Mutable state for one quiz room.

    Instances are created through :meth:`GameEngine.create_match`. Public
    fields are useful to a lobby adapter for snapshots, but game mutations must
    go through ``GameEngine`` methods so the shared room lock is respected.
    """

    room_id: str
    quiz_id: str
    questions: tuple[dict[str, Any], ...]
    player_names: dict[str, str]
    scores: dict[str, int]
    connected_players: set[str]
    phase: str = WAITING
    question_index: int = -1
    question_deadline: float | None = None
    answers: dict[str, str] = field(default_factory=dict)
    room_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    wake_event: threading.Event = field(default_factory=threading.Event, repr=False)
    stop_event: threading.Event = field(default_factory=threading.Event, repr=False)
    game_thread: threading.Thread | None = field(default=None, repr=False)


class GameEngine:
    """Run independent timed quiz matches and emit application-layer events.

    ``emit_event(room_id, event, data)`` is intentionally injected. In the
    server integration it should snapshot that room's ``ClientSession`` list
    and call ``Server.broadcast_event`` *after* its lobby lock is released.
    """

    def __init__(
        self,
        emit_event: EventEmitter,
        *,
        clock: Clock = time.monotonic,
        min_players: int = 2,
    ) -> None:
        if min_players < 1:
            raise ValueError("min_players must be at least one")
        self._emit_event = emit_event
        self._clock = clock
        self._min_players = min_players

    def create_match(
        self,
        room_id: str,
        quiz_id: str,
        questions: Iterable[Mapping[str, Any]],
        players: Mapping[str, Any] | Iterable[Mapping[str, Any]],
        *,
        room_lock: threading.RLock | None = None,
    ) -> MatchState:
        """Create isolated state from a validated lobby room snapshot.

        ``players`` accepts either ``{user_id: display_name}`` (or metadata
        mappings) or an iterable of ``{"user_id": ..., "display_name": ...}``
        records. B should pass its room's lock as ``room_lock`` so room and game
        updates use the same critical section. The
        questions are copied so later question-bank changes cannot affect a
        running game.
        """
        if not isinstance(room_id, str) or not room_id:
            raise ValueError("room_id must be a non-empty string")
        if not isinstance(quiz_id, str) or not quiz_id:
            raise ValueError("quiz_id must be a non-empty string")

        copied_questions = tuple(
            self._normalise_question(question, index)
            for index, question in enumerate(questions)
        )
        if not copied_questions:
            raise ValueError("a match needs at least one question")

        player_names = self._normalise_players(players)
        if not player_names:
            raise ValueError("a match needs at least one player")

        return MatchState(
            room_id=room_id,
            quiz_id=quiz_id,
            questions=copied_questions,
            player_names=player_names,
            scores={user_id: 0 for user_id in player_names},
            connected_players=set(player_names),
            room_lock=room_lock if room_lock is not None else threading.RLock(),
        )

    def start_match(self, match: MatchState, *, run_async: bool = True) -> dict[str, Any]:
        """Open question one and, normally, start its background timing loop.

        The immediate value is suitable for the frozen-v2 ``start`` response;
        ``game_started`` and ``question_open`` are sent as asynchronous events. Set
        ``run_async=False`` only for deterministic tests or a manual driver.
        """
        with match.room_lock:
            if match.phase != WAITING:
                return self._rejection("ALREADY_STARTED", "the game has already started")
            if len(match.connected_players) < self._min_players:
                return self._rejection(
                    "NOT_ALL_READY",
                    f"at least {self._min_players} connected players are required",
                )

            match.phase = RUNNING
            match.question_index = 0
            match.answers.clear()
            match.stop_event.clear()
            match.wake_event.clear()
            match.question_deadline = self._clock() + match.questions[0]["time_limit"]
            question_event = self._question_payload_locked(match)
            start_event = {
                "room_id": match.room_id,
                "quiz_id": match.quiz_id,
                "question_count": len(match.questions),
            }

        self._emit("game_started", match.room_id, start_event)
        self._emit("question_open", match.room_id, question_event)

        if run_async:
            worker = threading.Thread(
                target=self._run_match,
                args=(match,),
                name=f"quiz-{match.room_id}",
                daemon=True,
            )
            with match.room_lock:
                match.game_thread = worker
            worker.start()

        return {
            "accepted": True,
            "data": {
                "room_id": match.room_id,
                "state": "running",
                "question_count": len(match.questions),
            },
        }

    def submit_answer(
        self, match: MatchState, user_id: str, question_id: str, choice: str
    ) -> dict[str, Any]:
        """Store one in-time answer; never expose correctness before closure."""
        with match.room_lock:
            if match.phase != RUNNING:
                return self._rejection("LATE_ANSWER", "there is no open question")
            if user_id not in match.scores:
                return self._rejection("NOT_IN_ROOM", "player is not in this room")
            if user_id not in match.connected_players:
                return self._rejection("NOT_IN_ROOM", "player is no longer in this room")

            question = match.questions[match.question_index]
            if question_id != question["question_id"]:
                return self._rejection("INVALID_MESSAGE", "question_id is not the open question")
            if not isinstance(choice, str) or choice not in question["options"]:
                return self._rejection("INVALID_CHOICE", "choice must be one of A, B, C or D")
            if match.question_deadline is None or self._clock() >= match.question_deadline:
                return self._rejection("LATE_ANSWER", "the answer deadline has passed")
            if user_id in match.answers:
                return self._rejection("DUPLICATE_ANSWER", "only the first answer is accepted")

            match.answers[user_id] = choice
            if self._all_connected_players_answered_locked(match):
                match.wake_event.set()

        return {"accepted": True, "data": {"accepted": True}}

    def disconnect_player(self, match: MatchState, user_id: str) -> bool:
        """Mark a player disconnected without losing their earned score.

        Missing answers are worth zero. If every remaining connection has
        already answered, the timer worker is woken to close the question.
        An empty room simply stops its worker; no events are sent to nobody.
        """
        with match.room_lock:
            if user_id not in match.connected_players:
                return False
            match.connected_players.remove(user_id)
            if not match.connected_players:
                match.stop_event.set()
                match.wake_event.set()
            elif match.phase == RUNNING and self._all_connected_players_answered_locked(match):
                match.wake_event.set()
            return True

    def close_current_question(self, match: MatchState, *, force: bool = False) -> bool:
        """Close an active question and emit result plus next event(s).

        Production timing calls this with ``force=True`` only after the timer
        fires or all active clients have answered. The guard prevents an
        accidental early close from another integration module.
        """
        with match.room_lock:
            if match.phase != RUNNING or match.question_deadline is None:
                return False
            if (
                not force
                and self._clock() < match.question_deadline
                and not self._all_connected_players_answered_locked(match)
            ):
                return False
            events = self._settle_question_locked(match)

        for event, payload in events:
            self._emit(event, match.room_id, payload)
        return True

    def stop_match(self, match: MatchState, *, join_timeout: float = 1.0) -> None:
        """Wake and stop a game's timing worker (for server shutdown)."""
        with match.room_lock:
            match.stop_event.set()
            match.wake_event.set()
            match.answers.clear()
            match.question_deadline = None
            worker = match.game_thread
        if worker is not None and worker is not threading.current_thread():
            worker.join(join_timeout)

    def snapshot(self, match: MatchState) -> dict[str, Any]:
        """Return detached state for diagnostics or a room-update adapter."""
        with match.room_lock:
            return {
                "room_id": match.room_id,
                "quiz_id": match.quiz_id,
                "phase": match.phase,
                "question_index": match.question_index,
                "scores": dict(match.scores),
                "connected_players": sorted(match.connected_players),
                "answers_received": sorted(match.answers),
            }

    def _run_match(self, match: MatchState) -> None:
        """Wait for a deadline/all answers, then settle one question."""
        while True:
            with match.room_lock:
                if match.stop_event.is_set() or match.phase != RUNNING:
                    return
                deadline = match.question_deadline
                if deadline is None:
                    return
                remaining = max(0.0, deadline - self._clock())

            match.wake_event.wait(remaining)
            match.wake_event.clear()

            with match.room_lock:
                if match.stop_event.is_set() or match.phase != RUNNING:
                    return
                should_close = (
                    match.question_deadline is not None
                    and (
                        self._clock() >= match.question_deadline
                        or self._all_connected_players_answered_locked(match)
                    )
                )
            if should_close:
                self.close_current_question(match, force=True)

    def _settle_question_locked(self, match: MatchState) -> list[tuple[str, dict[str, Any]]]:
        """Apply points and construct public events while ``room_lock`` is held."""
        question = match.questions[match.question_index]
        correct_answer = question["answer"]
        for user_id, answer in match.answers.items():
            if answer == correct_answer:
                match.scores[user_id] += question["points"]

        result = {
            "room_id": match.room_id,
            "question_id": question["question_id"],
            "correct": correct_answer,
            "scores": dict(match.scores),
        }
        match.answers.clear()
        match.question_deadline = None
        match.wake_event.clear()
        events: list[tuple[str, dict[str, Any]]] = [("question_closed", result)]

        match.question_index += 1
        if match.question_index == len(match.questions):
            match.phase = FINISHED
            events.append(
                (
                    "game_finished",
                    {
                        "room_id": match.room_id,
                        "leaderboard": build_leaderboard(
                            match.scores,
                            match.player_names,
                        ),
                    },
                )
            )
            return events

        next_question = match.questions[match.question_index]
        match.question_deadline = self._clock() + next_question["time_limit"]
        events.append(("question_open", self._question_payload_locked(match)))
        return events

    def _question_payload_locked(self, match: MatchState) -> dict[str, Any]:
        """Return only fields a client may know while the question is open."""
        question = match.questions[match.question_index]
        return {
            "room_id": match.room_id,
            "question_id": question["question_id"],
            "text": question["text"],
            "options": dict(question["options"]),
            "time_limit": question["time_limit"],
            "points": question["points"],
            "index": match.question_index,
        }

    @staticmethod
    def _all_connected_players_answered_locked(match: MatchState) -> bool:
        return bool(match.connected_players) and match.connected_players.issubset(match.answers)

    @staticmethod
    def _rejection(code: str, message: str) -> dict[str, Any]:
        return {"accepted": False, "error": {"code": code, "message": message}}

    def _emit(self, event: str, room_id: str, data: dict[str, Any]) -> None:
        """Emit outside match locks; a slow socket must not stall scoring."""
        self._emit_event(room_id, event, data)

    @staticmethod
    def _normalise_question(question: Mapping[str, Any], index: int) -> dict[str, Any]:
        if not isinstance(question, Mapping):
            raise ValueError(f"question {index} must be an object")
        for field_name in ("question_id", "text", "answer"):
            if not isinstance(question.get(field_name), str) or not question[field_name]:
                raise ValueError(f"question {index} has invalid {field_name}")
        options = question.get("options")
        if not isinstance(options, Mapping) or not options:
            raise ValueError(f"question {index} needs non-empty options")
        copied_options = dict(options)
        if question["answer"] not in copied_options:
            raise ValueError(f"question {index} answer must be an option key")
        time_limit = question.get("time_limit")
        points = question.get("points")
        if isinstance(time_limit, bool) or not isinstance(time_limit, (int, float)) or time_limit <= 0:
            raise ValueError(f"question {index} has invalid time_limit")
        if isinstance(points, bool) or not isinstance(points, int) or points < 0:
            raise ValueError(f"question {index} has invalid points")
        return {
            "question_id": question["question_id"],
            "text": question["text"],
            "options": copied_options,
            "answer": question["answer"],
            "time_limit": time_limit,
            "points": points,
        }

    @staticmethod
    def _normalise_players(
        players: Mapping[str, Any] | Iterable[Mapping[str, Any]]
    ) -> dict[str, str]:
        names: dict[str, str] = {}
        if isinstance(players, Mapping):
            for user_id, details in players.items():
                if not isinstance(user_id, str) or not user_id:
                    raise ValueError("player user_id must be a non-empty string")
                name = (
                    details.get("display_name", details.get("name", user_id))
                    if isinstance(details, Mapping)
                    else details
                )
                names[user_id] = str(name) if name is not None else user_id
            return names

        for details in players:
            if not isinstance(details, Mapping):
                raise ValueError("player record must be an object")
            user_id = details.get("user_id")
            if not isinstance(user_id, str) or not user_id:
                raise ValueError("player user_id must be a non-empty string")
            if user_id in names:
                raise ValueError(f"duplicate player user_id: {user_id}")
            name = details.get("display_name", details.get("name", user_id))
            names[user_id] = str(name) if name is not None else user_id
        return names

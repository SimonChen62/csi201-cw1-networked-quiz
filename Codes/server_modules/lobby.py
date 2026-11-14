"""B: users, rooms, host and ready rules + the business request router.

This module owns everything between A's network layer and C's game engine:

    hello / list_quizzes / list_rooms / create_room / join_room /
    inspect_room / ready / start_game / answer / leave_room / quit

Integration signature (this is the answer to task C-01, "B supplies the business
request handler and the disconnect cleanup function")::

    request_handler, on_disconnect = create_business_handler(question_bank)
    Server(host, port, request_handler=request_handler,
           on_disconnect=on_disconnect, question_bank=question_bank)

``request_handler(session, message)`` returns one complete response dictionary;
A sends it. Never send the same reply from here as well.

Locking
-------
``self._lock`` protects the user table and the room table. ``room.lock`` is the
same ``threading.RLock`` that C's ``GameEngine`` uses for that room, so a room
and its match change inside one critical section. Network sends always happen
after the locks are released (A's ``send_event`` may block on a slow client).

Team rules implemented here (they must be described in the report as team design
decisions, not as Specification requirements):
    * at least 2 players and every current player ready before the host starts;
    * only the host may start, and only while the room is WAITING;
    * a player may sit in one room at a time; create_room/join_room first leave
      a WAITING room, but a RUNNING room refuses the move (ALREADY_STARTED);
    * when the host leaves, the host role moves to the smallest remaining
      ``user_id`` so the outcome is deterministic;
    * ``hello`` accepts 1-64 visible characters for both ``user_id`` and ``name``;
    * PLAYER lists are sorted by ``user_id``.

Event names come from C's engine unchanged. C still emits the v2 names
(``game_started`` / ``question_open`` / ``question_closed`` / ``game_finished``);
per CW1 6.1 C changes them to ``question`` / ``question_result`` /
``leaderboard``. B does not translate them here.
"""

import threading
from dataclasses import dataclass, field

try:  # imported as ``server_modules.lobby`` from Codes/
    from server_modules.game_engine import GameEngine
except ImportError:  # imported with ``server_modules`` already on sys.path
    try:
        from game_engine import GameEngine
    except ImportError:  # pragma: no cover - engine absent, start_game reports it
        GameEngine = None

WAITING = "WAITING"
RUNNING = "RUNNING"
FINISHED = "FINISHED"

MAX_IDENT_LENGTH = 64
MIN_PLAYERS = 2
OPEN_COMMANDS = frozenset({"hello", "echo", "quit"})


@dataclass
class Player:
    """One authenticated user; the same object is stored in the room it sits in."""

    user_id: str
    display_name: str
    session: object
    ready: bool = False


@dataclass
class Room:
    """One quiz room; ``lock`` is shared with that room's ``MatchState``."""

    room_id: str
    quiz_id: str
    host_user_id: str
    state: str = WAITING
    players: dict = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    match: object = None


def _response(request_id, data):
    return {"type": "response", "request_id": request_id, "ok": True, "data": data}


def _error(request_id, code, message):
    return {
        "type": "response",
        "request_id": request_id,
        "ok": False,
        "error": {"code": code, "message": message},
    }


def _visible_length(value):
    return sum(1 for char in value if char.isprintable() and not char.isspace())


class Lobby:
    """Own the user table, the room table and the request router."""

    def __init__(self, question_bank, engine=None, engine_factory=None, min_players=MIN_PLAYERS):
        """Build the lobby; C's engine is wired around this lobby's emitter."""
        self._bank = question_bank
        self._lock = threading.RLock()
        self._users = {}          # user_id -> Player
        self._by_session = {}     # session -> user_id
        self._rooms = {}          # room_id -> Room
        self._room_counter = 0
        self._min_players = max(MIN_PLAYERS, int(min_players))

        if engine is not None:
            self._engine = engine
        elif engine_factory is not None:
            self._engine = engine_factory(self._emit_event)
        elif GameEngine is not None:
            # C's engine emits into this lobby; it must not be built with a
            # different emitter or events would never reach the clients.
            self._engine = GameEngine(emit_event=self._emit_event, min_players=self._min_players)
        else:  # pragma: no cover
            self._engine = None

    # ------------------------------------------------------------------ wiring
    def event_emitter(self):
        """Return the ``emit_event(room_id, event, data)`` callable for C."""
        return self._emit_event

    def handle_request(self, session, message):
        """A's single business entry point: always returns one response dict."""
        request_id = message.get("request_id")
        message_type = message.get("type")
        if not isinstance(message_type, str):
            return _error(request_id, "INVALID_MESSAGE", "type must be a string")

        user_id = self._by_session.get(session)
        if user_id is None and message_type not in OPEN_COMMANDS:
            return _error(request_id, "NOT_AUTHENTICATED", "send hello before other commands")

        handler = {
            "hello": self._hello,
            "echo": self._echo,
            "list_quizzes": self._list_quizzes,
            "list_rooms": self._list_rooms,
            "create_room": self._create_room,
            "join_room": self._join_room,
            "inspect_room": self._inspect_room,
            "ready": self._ready,
            "start_game": self._start_game,
            "answer": self._answer,
            "leave_room": self._leave_room,
            "quit": self._quit,
        }.get(message_type)
        if handler is None:
            return _error(request_id, "UNKNOWN_COMMAND", f"unsupported message type: {message_type}")

        try:
            response, events = handler(session, request_id, message, user_id)
        except Exception as exc:  # a business bug must not kill the connection
            print(f"business handler failed on {message_type}: {exc!r}", flush=True)
            return _error(request_id, "INTERNAL_ERROR", "business handler failed")

        for targets, event_name, data in events:
            self._send(targets, event_name, data)
        return response

    def on_disconnect(self, session):
        """A's cleanup callback: forget the identity and free the room seat."""
        events = []
        with self._lock:
            user_id = self._by_session.pop(session, None)
            if user_id is None:
                return
            self._users.pop(user_id, None)
            room = self._room_of(user_id)
            if room is not None:
                events = self._remove_player(room, user_id)
        for targets, event_name, data in events:
            self._send(targets, event_name, data)

    # ------------------------------------------------------------------ events
    def _emit_event(self, room_id, event, data):
        """C's emitter: copy the recipient list, then send outside the lock."""
        with self._lock:
            room = self._rooms.get(room_id)
            targets = [player.session for player in room.players.values()] if room else []
        self._send(targets, event, data)

    @staticmethod
    def _send(targets, event_name, data):
        for session in targets:
            session.send_event(event_name, data)

    # ------------------------------------------------------------------ helpers
    def _room_of(self, user_id):
        """Return the room the user currently sits in, or ``None``."""
        for room in self._rooms.values():
            if user_id in room.players:
                return room
        return None

    def _room_state(self, room):
        """Derive the room phase; a running match is authoritative once created."""
        if room.match is None:
            return room.state
        with room.lock:
            return room.match.phase

    def _room_view(self, room):
        """Build the v3 ROOM object (players sorted by user_id)."""
        if room.match is None:
            scores = {}
        else:
            with room.lock:
                scores = dict(room.match.scores)
        players = [
            {
                "user_id": player.user_id,
                "display_name": player.display_name,
                "ready": bool(player.ready),
                "score": int(scores.get(player.user_id, 0)),
            }
            for player in sorted(room.players.values(), key=lambda item: item.user_id)
        ]
        return {
            "room_id": room.room_id,
            "quiz_id": room.quiz_id,
            "host_user_id": room.host_user_id,
            "state": self._room_state(room),
            "players": players,
        }

    def _targets(self, room):
        return [player.session for player in room.players.values()]

    def _detach_from_other_room(self, user_id):
        """Remove the user from any room it holds; return pending events."""
        room = self._room_of(user_id)
        if room is None:
            return []
        if self._room_state(room) != WAITING:
            raise _Conflict("ALREADY_STARTED", "you are already in a running room")
        return self._remove_player(room, user_id)

    def _remove_player(self, room, user_id):
        """Drop one seat, transfer host, delete an empty room; return events."""
        player = room.players.pop(user_id, None)
        if player is not None:
            player.ready = False
        if room.match is not None and self._engine is not None:
            self._engine.disconnect_player(room.match, user_id)

        if room.host_user_id == user_id and room.players:
            room.host_user_id = min(room.players.keys())
        if not room.players:
            self._rooms.pop(room.room_id, None)
            return []

        return [(self._targets(room), "room_update", self._room_view(room))]

    def _require_text_field(self, message, field_name, request_id):
        value = message.get(field_name)
        if not isinstance(value, str) or _visible_length(value) < 1:
            raise _BadRequest(request_id, field_name, "must be a non-empty string")
        return value

    # ------------------------------------------------------------------ commands
    def _hello(self, session, request_id, message, user_id):
        raw_id = message.get("user_id")
        raw_name = message.get("name")
        if not isinstance(raw_id, str) or _visible_length(raw_id) < 1:
            return _error(request_id, "INVALID_MESSAGE", "user_id must be a non-empty string"), []
        if not isinstance(raw_name, str) or _visible_length(raw_name) < 1:
            return _error(request_id, "INVALID_MESSAGE", "name must be a non-empty string"), []
        display_name = raw_name.strip()
        user_id_new = raw_id.strip()
        if len(user_id_new) > MAX_IDENT_LENGTH or len(display_name) > MAX_IDENT_LENGTH:
            return (
                _error(
                    request_id,
                    "INVALID_MESSAGE",
                    f"user_id and name must be at most {MAX_IDENT_LENGTH} characters",
                ),
                [],
            )

        with self._lock:
            if session in self._by_session:
                return _error(request_id, "INVALID_MESSAGE", "this session already logged in"), []
            if user_id_new in self._users:
                return (
                    _error(request_id, "DUPLICATE_USER", f"user_id {user_id_new!r} is already active"),
                    [],
                )
            player = Player(user_id=user_id_new, display_name=display_name, session=session)
            self._users[user_id_new] = player
            self._by_session[session] = user_id_new

        # v3 keeps the hello response keys aligned with the request; the internal
        # value is display_name and every PLAYER/leaderboard uses display_name.
        return _response(request_id, {"user_id": user_id_new, "name": display_name}), []

    def _echo(self, session, request_id, message, user_id):
        text = message.get("text")
        if not isinstance(text, str):
            return _error(request_id, "INVALID_MESSAGE", "text must be a string"), []
        return _response(request_id, {"text": text}), []

    def _list_quizzes(self, session, request_id, message, user_id):
        if not hasattr(self._bank, "public_list"):
            return _error(request_id, "INTERNAL_ERROR", "question bank is not available"), []
        return _response(request_id, {"quizzes": self._bank.public_list()}), []

    def _list_rooms(self, session, request_id, message, user_id):
        with self._lock:
            rooms = [
                {
                    "room_id": room.room_id,
                    "quiz_id": room.quiz_id,
                    "host_user_id": room.host_user_id,
                    "state": self._room_state(room),
                    "player_count": len(room.players),
                }
                for room in self._rooms.values()
            ]
        return _response(request_id, {"rooms": rooms}), []

    def _create_room(self, session, request_id, message, user_id):
        quiz_id = message.get("quiz_id")
        if not isinstance(quiz_id, str) or not quiz_id:
            return _error(request_id, "INVALID_MESSAGE", "quiz_id must be a non-empty string"), []
        if not hasattr(self._bank, "get_quiz"):
            return _error(request_id, "INTERNAL_ERROR", "question bank is not available"), []

        with self._lock:
            quiz = self._bank.get_quiz(quiz_id)
            if quiz is None:
                return _error(request_id, "QUIZ_NOT_FOUND", f"quiz {quiz_id!r} does not exist"), []

            player = self._users[user_id]
            try:
                events = self._detach_from_other_room(user_id)
            except _Conflict as conflict:
                return _error(request_id, conflict.code, conflict.message), []

            self._room_counter += 1
            room = Room(room_id=f"R{self._room_counter}", quiz_id=quiz.quiz_id, host_user_id=user_id)
            player.ready = False
            room.players[user_id] = player
            self._rooms[room.room_id] = room
            return _response(request_id, {"room": self._room_view(room)}), events

    def _join_room(self, session, request_id, message, user_id):
        room_id = message.get("room_id")
        if not isinstance(room_id, str) or not room_id:
            return _error(request_id, "INVALID_MESSAGE", "room_id must be a non-empty string"), []

        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return _error(request_id, "ROOM_NOT_FOUND", f"room {room_id!r} does not exist"), []
            if user_id in room.players:
                return _response(request_id, {"room": self._room_view(room)}), []
            if self._room_state(room) != WAITING:
                return _error(request_id, "ALREADY_STARTED", "this room has already started"), []

            player = self._users[user_id]
            try:
                events = self._detach_from_other_room(user_id)
            except _Conflict as conflict:
                return _error(request_id, conflict.code, conflict.message), []

            player.ready = False
            room.players[user_id] = player
            view = self._room_view(room)
            events.append((self._targets(room), "room_update", view))
            return _response(request_id, {"room": view}), events

    def _inspect_room(self, session, request_id, message, user_id):
        room_id = message.get("room_id")
        if not isinstance(room_id, str) or not room_id:
            return _error(request_id, "INVALID_MESSAGE", "room_id must be a non-empty string"), []

        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return _error(request_id, "ROOM_NOT_FOUND", f"room {room_id!r} does not exist"), []
            if user_id not in room.players:
                return _error(request_id, "NOT_IN_ROOM", "you are not in this room"), []
            return _response(request_id, {"room": self._room_view(room)}), []

    def _ready(self, session, request_id, message, user_id):
        room_id = message.get("room_id")
        ready = message.get("ready")
        if not isinstance(room_id, str) or not room_id:
            return _error(request_id, "INVALID_MESSAGE", "room_id must be a non-empty string"), []
        if not isinstance(ready, bool):
            return _error(request_id, "INVALID_MESSAGE", "ready must be true or false"), []

        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return _error(request_id, "ROOM_NOT_FOUND", f"room {room_id!r} does not exist"), []
            if user_id not in room.players:
                return _error(request_id, "NOT_IN_ROOM", "you are not in this room"), []
            if self._room_state(room) != WAITING:
                return _error(request_id, "ALREADY_STARTED", "this room has already started"), []

            room.players[user_id].ready = ready
            view = self._room_view(room)
            return _response(request_id, {"room": view}), [(self._targets(room), "room_update", view)]

    def _start_game(self, session, request_id, message, user_id):
        room_id = message.get("room_id")
        if not isinstance(room_id, str) or not room_id:
            return _error(request_id, "INVALID_MESSAGE", "room_id must be a non-empty string"), []
        engine = self._engine
        if engine is None or not hasattr(engine, "create_match"):
            return _error(request_id, "INTERNAL_ERROR", "game engine is not configured"), []

        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return _error(request_id, "ROOM_NOT_FOUND", f"room {room_id!r} does not exist"), []
            if user_id not in room.players:
                return _error(request_id, "NOT_IN_ROOM", "you are not in this room"), []
            if room.host_user_id != user_id:
                return _error(request_id, "NOT_HOST", "only the host may start the game"), []
            if self._room_state(room) != WAITING or room.match is not None:
                return _error(request_id, "ALREADY_STARTED", "this room has already started"), []
            if len(room.players) < self._min_players:
                return (
                    _error(
                        request_id,
                        "NOT_ALL_READY",
                        f"at least {self._min_players} players are required",
                    ),
                    [],
                )
            if not all(player.ready for player in room.players.values()):
                return _error(request_id, "NOT_ALL_READY", "every player must be ready"), []

            quiz = self._bank.get_quiz(room.quiz_id)
            if quiz is None:
                return _error(request_id, "QUIZ_NOT_FOUND", "the room quiz no longer exists"), []

            names = {uid: player.display_name for uid, player in room.players.items()}
            try:
                match = engine.create_match(
                    room.room_id,
                    room.quiz_id,
                    quiz.question_payloads(),
                    names,
                    room_lock=room.lock,
                )
            except ValueError as exc:
                return _error(request_id, "INTERNAL_ERROR", f"cannot create a match: {exc}"), []
            room.match = match

        # start_match runs outside the lobby lock: it emits the first question, and
        # A's send_event must never happen while the user/room table is locked.
        result = engine.start_match(match)
        if not result.get("accepted"):
            error = result.get("error") or {}
            with self._lock:
                room.match = None
            return (
                _error(
                    request_id,
                    error.get("code", "INTERNAL_ERROR"),
                    error.get("message", "the engine refused to start"),
                ),
                [],
            )

        with self._lock:
            room.state = RUNNING
        return _response(request_id, {}), []

    def _answer(self, session, request_id, message, user_id):
        room_id = message.get("room_id")
        question_id = message.get("question_id")
        choice = message.get("choice")
        if not isinstance(room_id, str) or not room_id:
            return _error(request_id, "INVALID_MESSAGE", "room_id must be a non-empty string"), []
        if not isinstance(question_id, str) or not question_id:
            return _error(request_id, "INVALID_MESSAGE", "question_id must be a non-empty string"), []
        if not isinstance(choice, str):
            return _error(request_id, "INVALID_CHOICE", "choice must be A, B, C or D"), []
        engine = self._engine
        if engine is None or not hasattr(engine, "submit_answer"):
            return _error(request_id, "INTERNAL_ERROR", "game engine is not configured"), []

        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return _error(request_id, "ROOM_NOT_FOUND", f"room {room_id!r} does not exist"), []
            if user_id not in room.players:
                return _error(request_id, "NOT_IN_ROOM", "you are not in this room"), []
            match = room.match

        if match is None:
            return _error(request_id, "LATE_ANSWER", "there is no open question"), []

        result = engine.submit_answer(match, user_id, question_id, choice)
        if not result.get("accepted"):
            error = result.get("error") or {}
            return (
                _error(
                    request_id,
                    error.get("code", "INTERNAL_ERROR"),
                    error.get("message", "the answer was rejected"),
                ),
                [],
            )
        return _response(request_id, {"accepted": True}), []

    def _leave_room(self, session, request_id, message, user_id):
        room_id = message.get("room_id")
        if not isinstance(room_id, str) or not room_id:
            return _error(request_id, "INVALID_MESSAGE", "room_id must be a non-empty string"), []

        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return _error(request_id, "ROOM_NOT_FOUND", f"room {room_id!r} does not exist"), []
            if user_id not in room.players:
                return _error(request_id, "NOT_IN_ROOM", "you are not in this room"), []
            events = self._remove_player(room, user_id)
        return _response(request_id, {}), events

    def _quit(self, session, request_id, message, user_id):
        # v3: the server only confirms; the client closes its own socket and A's
        # disconnect callback performs the identity and room cleanup.
        return _response(request_id, {"bye": True}), []


class _BadRequest(Exception):
    def __init__(self, request_id, field_name, problem):
        super().__init__(f"{field_name} {problem}")
        self.request_id = request_id


class _Conflict(Exception):
    """Internal signal: the requested move conflicts with the current room state."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def create_business_handler(question_bank, engine=None, engine_factory=None, min_players=MIN_PLAYERS):
    """Return ``(request_handler, on_disconnect)`` for ``Server(...)``."""
    lobby = Lobby(
        question_bank,
        engine=engine,
        engine_factory=engine_factory,
        min_players=min_players,
    )
    return lobby.handle_request, lobby.on_disconnect

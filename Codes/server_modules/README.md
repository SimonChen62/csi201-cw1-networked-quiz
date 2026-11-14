# Server module ownership

These modules are separate from A's network entry point. Status as of 2026-11-14:

- `question_bank.py`: implemented in this branch by E as the requested integration prerequisite; B owns the ongoing question-bank/lobby interface. `load_question_bank(path)` validates the entire file and returns its top-level dictionary. Quizzes are in `bank["quizzes"]`, and questions in `quiz["questions"]`. Order and permitted extra members are preserved. See [the API and validation rules](../README.md).
- `lobby.py`: still a placeholder; B must implement users, rooms, host and ready state and provide business/disconnect handlers.
- `game_engine.py` / `scoring.py`: C's match timing, answers, scores and leaderboard are implemented with 7 module tests. Event names still need alignment with the group's v3 target and the real client.

The loader contains correct answers and is server-only. Do not serialize its return value directly to clients; build public catalog and question messages explicitly. Invalid schema/encoding/JSON raises `ValueError`; file-access failures raise `OSError`. The existing `server.main()` now loads and validates before creating the listening socket.

Loading the bank does not connect the lobby or game engine automatically. The default server still handles only echo. B/C handlers, broadcasts and disconnect/stop callbacks must be assembled in `server.py`; see [current validation and remaining work](../../docs/evidence/2026-11-14-question-bank-validation.md).

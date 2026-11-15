# Server module interfaces

The assessed server entry point is [server.py](../server.py). It validates the full bank, creates a Lobby, and supplies its request and disconnect callbacks to the TCP transport.

| Module | Responsibility and interface |
| --- | --- |
| `question_bank.py` | `load_question_bank(path)` returns a validated `QuestionBank`; file errors raise `OSError`, invalid content raises `ValueError` |
| `lobby.py` | Identities, rooms, readiness, host permissions, routing, and match lifecycle |
| `game_engine.py` | Per-room questions, monotonic deadlines, answer acceptance, and question/result/leaderboard events |
| `scoring.py` | Correct-answer points and deterministic ranking |

`bank.public_list()` returns safe catalogue metadata. `bank.get_quiz(quiz_id)` returns a quiz or None. `quiz.question_payloads()` creates question copies including answers for server-side engine use only; do not transmit those directly to clients.

`Lobby.handle_request(session, message)` returns one response dictionary for the transport to send. `Lobby.on_disconnect(session)` removes the identity and room seat. `create_business_handler(bank)` exposes the same two callbacks for callers that need a tuple.

The formal entry point retains the Lobby instance so shutdown can reject work and signal match timers, close the network and wait for connection cleanup, then wait for timer workers. Bank validation precedes all listener creation.

The lobby lock protects the identity/session/room tables. Each match shares its room's reentrant lock. Network sends occur outside business locks. See [PROTOCOL.md](../PROTOCOL.md) for fields, errors, lock ordering, and lifecycle, and [README.md](../README.md) for operation.

`tem_server.py` is an obsolete development experiment, is not imported by the assessed application or test suite, and must be excluded from the submission.

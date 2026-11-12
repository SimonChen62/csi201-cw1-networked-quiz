# Server module ownership

These files are reserved for B and C. They are separate from A's network entry point.

- `question_bank.py`: B, question-bank loading and validation.
- `lobby.py`: B, users, rooms, host and ready state.
- `game_engine.py`: C, questions, timing, answers, scores and leaderboard.
- `scoring.py`: C, deterministic final leaderboard construction.

The C module exposes `GameEngine` and `MatchState`:

- `create_match(room_id, quiz_id, questions, players)` creates isolated state;
- `start_match(match)` opens the first question and starts the room timer;
- `submit_answer(match, user_id, question_id, choice)` accepts or rejects one answer;
- `disconnect_player(match, user_id)` treats the current answer as missing;
- `stop_match(match)` wakes its timer for graceful server shutdown.

`GameEngine` receives an event callback and emits the frozen-v2 events
`game_started`, `question_open`, `question_closed` and `game_finished`. See
[`Documentation/contributions/C_game_engine.md`](../../Documentation/contributions/C_game_engine.md)
for the event fields and A/B integration contract. The current A/D code uses
`Server.broadcast_event`, which wraps these as generic `{"type":"event", ...}`
messages for the client receiver.

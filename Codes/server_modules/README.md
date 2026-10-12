# Server module ownership

These files are reserved for B and C. They are separate from A's network entry point.

- `question_bank.py`: B, question-bank loading and validation.
- `lobby.py`: B, users, rooms, host and ready state.
- `game_engine.py`: C, questions, timing, answers, scores and leaderboard.

The modules should expose small functions or classes that `server.py` can call. Agree on names and parameters before integrating.

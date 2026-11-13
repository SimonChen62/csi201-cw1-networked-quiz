# C — Game engine implementation note

## Delivered module

`Codes/server_modules/game_engine.py` owns one `MatchState` per active room.
The state accepts B's room lock, and has a question index, server-monotonic
deadline, accepted-answer map, total scores, connected-player set and one
daemon timer thread. `Codes/server_modules/scoring.py` produces a deterministic
leaderboard (score descending, then user ID).

This implements the agreed rules:

- questions remain in their JSON order;
- only the first on-time answer from each connected player is accepted;
- correct answers receive the question's configured points; wrong or missing
  answers receive zero;
- late and duplicate answers are rejected;
- a disconnect does not stop the room or erase points already earned;
- different rooms have separate state and cannot share answers or scores.

`question_open` deliberately contains neither `answer` nor `correct`. The
correct answer first appears in `question_closed`, after that question is
settled.

## Frozen v2 contract

This module follows the group's frozen-v2 message table:

- `start_match` emits `game_started`, then `question_open`;
- `question_open` uses `index`, not `question_index`;
- closed-question data uses `correct`, not `answer`;
- the final event is `game_finished`, not `leaderboard`;
- an answer request uses the field and parameter name `choice`;
- errors use `INVALID_CHOICE`, `LATE_ANSWER`, `DUPLICATE_ANSWER`,
  `NOT_IN_ROOM` or `INVALID_MESSAGE` as appropriate.

## Integration contract for A and B

1. After B has checked host, ready state and minimum players, build one match:

   ```python
   match = engine.create_match(
       room.room_id, room.quiz_id, questions, players, room_lock=room.room_lock
   )
   active_matches[room.room_id] = match
   result = engine.start_match(match)
   ```

   `players` may be `{user_id: {"display_name": display_name}}` or a list of
   `{"user_id": ..., "display_name": ...}` records. `questions` is the
   selected server-side quiz list, including answers; the engine never sends an
   answer in a question event. B must finish the host, two-player and
   all-ready checks before calling `start_match`.

2. For an `answer` request, call:

   ```python
   result = engine.submit_answer(match, session.user_id, question_id, choice)
   ```

   Return a normal response with `ok: true` when `result["accepted"]` is true;
   otherwise put `result["error"]` in the project's normal `ok: false`
   response. Do not calculate a score in the request handler.

3. The engine constructor needs an event bridge. With the current network code,
   its callback should snapshot the target room sessions and call
   `server.broadcast_event(targets, event, data)`. That function currently
   creates the message wrapper consumed by D:

   ```json
   {"type":"event", "event":"question_open", "data": {"room_id":"...", "question_id":"..."}}
   ```

   Never hold B's lobby lock while broadcasting to sockets.

4. From A's disconnect callback, look up the active match for the room and
   call `engine.disconnect_player(match, user_id)`. From orderly server
   shutdown, call `engine.stop_match(match)` for each active match before
   closing sockets.

## Event payloads sent by C

| Event | Required fields |
| --- | --- |
| `game_started` | `room_id`, `quiz_id`, `question_count` |
| `question_open` | `room_id`, `question_id`, `index`, `text`, `options`, `time_limit`, `points` |
| `question_closed` | `room_id`, `question_id`, `correct`, `scores` |
| `game_finished` | `room_id`, `leaderboard` (`rank`, `user_id`, `display_name`, `score`) |

## Tests and evidence

`Codes/tests/test_game_engine.py` uses a fake clock and callback (so it needs
no sockets) to test correct/wrong scoring, duplicate and late rejection,
disconnects, room isolation, two-room ten-player state, minimum players and a
real timer-thread deadline. Run from `Codes` with:

```bash
python3 -m unittest tests.test_game_engine -v
```

The final verification still needs A/B/E integration and the official examiner
Docker image; this unit-test file is not evidence that complete TCP flows have
been tested.

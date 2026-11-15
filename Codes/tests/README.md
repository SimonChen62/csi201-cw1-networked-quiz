# Test guide

Run from the Codes directory inside the course Docker image:

```sh
python3 -B -m unittest discover -s tests -v
```

The suite contains 146 tests. See the project [README](../README.md) for startup commands.

| Scope | Files | Coverage |
| --- | --- | --- |
| Network layer: 29 tests | test_protocol/server/dispatch/disconnect/startup/network.py | Encoding, framing, sending, routing, shutdown, and real TCP; some use lab-mode |
| D connection/state: 13 tests | test_connection.py, test_state.py | Requests, events, fragmentation, timeouts, and state isolation |
| D/E regressions: 14 tests | test_client_regressions.py, test_cli.py | Client regressions and real CLI processes with scripted test peers |
| B question bank: 31 tests | test_question_bank.py | Typed bank objects, schema, types, ranges, and public catalogue |
| B lobby: 39 tests | test_lobby.py | Identity, rooms, readiness, host permissions, and cleanup; uses StubEngine |
| C engine: 7 tests | test_game_engine.py | Timing, scoring, duplicate/late answers, ranking, and isolation |
| Integration regressions: 8 tests | test_integration_regressions.py | Loader boundaries, validation before socket creation, start races, failed sends, and timer shutdown |
| Paired system: 5 tests | test_paired_system.py | Real server.py and client.py subprocesses, as described below |

The five paired acceptance scenarios are:

1. Two real CLI players complete the shipped quiz, including duplicate login, host/readiness checks, duplicate answers, scores, ranking, and normal exit.
2. The formal server loads questions_50.json; a real client logs in and lists five quizzes with ten questions each.
3. Ten real CLI clients complete matches in two rooms with separate questions, results, and scores; all clients exit normally.
4. A separate ten-client run terminates one client unexpectedly; the remaining players in both rooms continue.
5. The formal server receives diagnostic TCP input covering malformed JSON, NaN, nested malformed JSON, unknown commands, answer confidentiality, a five-second server deadline, missing/old answers, oversized-frame isolation, and SIGINT during an active match. A real CLI observer exits automatically.

Scenarios 3, 4, and 5 use a temporary valid bank with five-second deadlines permitted by the specification. The shipped bank is unchanged. WirePeer injects malformed messages in scenario 5 and does not count toward the ten-client evidence. process_support.py manages subprocess input/output, waiting, and cleanup.

Set QUIZ_EVIDENCE_DIR to save server/client transcripts and the bank used in each scenario. Cleanup records actual process exit codes. A client deliberately killed by the test retains its nonzero exit record; other clients and the server must exit normally.

Manual demonstrations and the team video are separate activities. Automated terminal input does not replace each member explaining their own implementation.

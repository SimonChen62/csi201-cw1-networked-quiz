# Automated test guide

## 1. Running and interpreting the suite

From `Codes` inside the course Docker environment:

```sh
python3 -B -m unittest discover -s tests -v
```

The suite has **146 test methods in 15 files**. These are project checks, not 146 teacher-prescribed tasks. Each method may contain several assertions or parameter subcases. `-B` avoids bytecode cache writes; `discover -s tests` finds test files; `-v` prints each method and its result.

The harness starts its own servers on available ports, feeds input, checks replies, and cleans up subprocesses. You do not need to start a manual server. Tests require no installed third-party packages. The paired SIGINT/process checks are intended for the Linux course container.

Success ends in `Ran 146 tests ... OK` and exit status 0. `FAIL` is a failed assertion; `ERROR` is an exception that prevented a test completing. Deliberate encoding/send/cleanup error logs are expected in failure-injection tests; the result word and final summary decide whether the test passed.

## 2. Exact inventory and evidence boundaries

| Test file | Methods | What it checks | How it runs |
| --- | ---: | --- | --- |
| `test_protocol.py` | 4 | UTF-8 round trips, newline framing, partial/coalesced messages, malformed and oversized data | Direct encoder/decoder calls |
| `test_server.py` | 4 | Successful sends, encoding errors, closed sockets, concurrent frame writes | Controlled connections and socket pairs |
| `test_dispatch.py` | 3 | Handler dispatch, events versus replies, targeted broadcast and failed recipients | Socket pairs and a temporary-client reader |
| `test_disconnect.py` | 8 | Idempotent close, read unblocking, callback isolation, failed sends and shutdown waiting | Socket pairs and worker threads |
| `test_startup.py` | 7 | Required arguments, bank loading before listening, rejection, lab mode and ready marker | Injected loader/server objects plus a real listener |
| `test_network.py` | 3 | Two/ten independent connections and recoverable malformed input on one connection | Real TCP against transport-only lab mode; does not prove room isolation |
| `test_connection.py` | 6 | Handshake, fragmented/coalesced messages, events, disconnects, timeout and error envelopes | Client Connection with scripted FakeServer |
| `test_state.py` | 7 | Room/question transitions, answer confidentiality, snapshots, isolation and protocol fields | Direct ClientState checks |
| `test_client_regressions.py` | 11 | Pending-request cleanup, errors, timeout, delayed/stale/foreign events, snapshots and question context | Controlled connection/state interactions |
| `test_cli.py` | 3 | CLI workflow, asynchronous output while input is idle, remote closure and stdin EOF | Actual CLI subprocess with scripted single-client peer |
| `test_question_bank.py` | 31 | Valid bank and boundaries; invalid file/type/range/missing fields/duplicate IDs; safe public metadata | Real loader with temporary banks |
| `test_lobby.py` | 39 | Login, unique IDs, catalogue, room membership/host/readiness, routing, leave, quit and cleanup | FakeSession and StubEngine; does not test real timers |
| `test_game_engine.py` | 7 | Correct/wrong/missing/duplicate/late answers, deadlines, ranks, ten-player room isolation | Engine calls, controlled emitters, and timer threads |
| `test_integration_regressions.py` | 8 | Bank boundaries, invalid last question before socket creation, startup reservation, failed-recipient isolation and timer shutdown | Real components with controlled peers/selected mocks |
| `test_paired_system.py` | 5 | Actual server/client operation, two-player scoring, alternate bank, ten clients/two rooms, failure handling | Real subprocesses; diagnostic raw peers only where malformed input is required |
| **Total** | **146** | | |

Unit tests that inject a loader do not prove the real loader import works. The real bank integration and paired server-start checks provide that additional evidence. Ten lab-mode connections prove transport handling; the paired ten-client matches provide room/game evidence.

## 3. The five paired-system methods

1. `test_two_real_cli_clients_complete_shipped_quiz`: runs unmodified `questions.json`, starts Alice and Bob, rejects duplicate Alice and invalid quiz selection, checks host/readiness gates, completes all five questions with correct/wrong answers, rejects a repeated answer, verifies exact totals and ranking, leaves/quits, and checks clean server SIGINT.
2. `test_alternate_fifty_question_bank_supports_formal_login`: loads `questions_50.json`, starts a real CLI client, checks five catalogue entries with ten questions each, and verifies shutdown/disconnect. This is additional project test data, not a task-sheet-mandated filename or a verified examiner test bank. Local file provenance is documented in the project README. This scenario does not play all 50 questions.
3. `test_ten_real_cli_clients_complete_both_rooms`: starts ten CLI processes, splits them five/five across two quizzes, completes both five-question matches, checks room-specific question/result sequences and different scores, and verifies normal exits.
4. `test_ten_real_cli_clients_two_rooms_isolation_and_disconnect`: repeats the two-room setup, deliberately kills one client, and checks the remaining clients continue to the expected results without cross-room leakage.
5. `test_deadline_bad_messages_and_sigint_during_active_game`: uses a real server, a real CLI observer, and two diagnostic WirePeer connections. It injects malformed JSON/NaN/deep malformed input and an unknown command; checks public-data confidentiality, a five-second deadline with a missing answer, old-question rejection, oversized-peer isolation, and SIGINT during play. WirePeer is not counted as a formal CLI player.

Scenarios 3-5 create a temporary valid copy of the default bank with five-second deadlines. The original bank is unchanged. The harness knows expected answers for assertions; the submitted client never opens a bank.

## 4. Running one area or one scenario

Only loader checks:

```sh
python3 -B -m unittest discover -s tests -p test_question_bank.py -v
```

All five paired checks:

```sh
python3 -B -m unittest discover -s tests -p test_paired_system.py -v
```

One two-player match, still from `Codes`:

```sh
PYTHONPATH=tests python3 -B -m unittest -v test_paired_system.PairedSystemTest.test_two_real_cli_clients_complete_shipped_quiz
```

Save paired evidence to a writable container directory:

```sh
QUIZ_EVIDENCE_DIR=/tmp/quiz-evidence python3 -B -m unittest discover -s tests -p test_paired_system.py -v
```

Each scenario directory contains process transcripts and the bank actually used. Cleanup records process exit codes; the deliberately killed client has a nonzero code, while the expected normal exits are checked. Without QUIZ_EVIDENCE_DIR, those persistent transcripts are not created.

## 5. Files that must remain with the tests

- `process_support.py`: subprocess input/output, bounded waits, cleanup, and diagnostic WirePeer.
- `fake_server.py`: scripted network peer imported by `test_connection.py`.
- `cli_demo_server.py`: scripted peer used by `test_cli.py`.
- `server_temp_test.py`: echo diagnostic client used by dispatch/network tests.
- `hold_connection_demo.py`: optional manual TCP shutdown observer; not part of test discovery.
- `../questions.json` and `../questions_50.json`: data files used by loader and paired tests.

Do not remove helper files just because their names do not start with test_. Development peers do not replace the assessed server/client. Test counts do not establish that the final PDF, video, archive structure, or every possible concurrency schedule has been checked; review those separately.

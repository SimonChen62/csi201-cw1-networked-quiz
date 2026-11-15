# Networked Quiz Tournament

A command-line quiz system implemented with Python 3.12 standard-library modules and raw TCP sockets. The server owns identities, rooms, question timing, scoring, and the question bank. Clients receive quiz information over TCP; they do not open question-bank files.

## 1. Environment and required launch commands

Run and verify the submission inside the examiner's Docker environment. No package installation, database, GUI, or network download is required. Run the following commands from the `Codes` directory mounted inside that environment.

Server, in terminal 1:

```sh
python3 server.py --host 127.0.0.1 --port 5000 --questions questions.json
```

Clients, in separate terminals in the same container:

```sh
python3 client.py --server 127.0.0.1 --port 5000 --id alice --name Alice
python3 client.py --server 127.0.0.1 --port 5000 --id bob --name Bob
```

| Argument | Meaning |
| --- | --- |
| Server `--host` | Local address on which the server binds |
| Server/client `--port` | TCP port; both sides must use the same port |
| Server `--questions` | Path to the JSON bank; relative paths are resolved from the working directory |
| Client `--server` | Server address reachable from that client |
| Client `--id` | Unique active user ID |
| Client `--name` | Display name; quote names containing spaces |

All arguments shown above are required for normal operation. The example port is selectable, not hard-coded. Server port `0` is used only by automated tests to request a free port. The development-only `--lab-mode` option runs an echo transport without a bank; it is not the quiz application and cannot be combined with `--questions`.

Successful validation followed by successful binding/listening produces:

```text
SERVER_READY 127.0.0.1 5000
```

A missing, unreadable, empty, oversized, malformed, or schema-invalid bank produces a meaningful diagnostic and exit status 1 before any listening socket is created. Omitting required arguments produces an argparse usage error and exit status 2. A client reports `[CONNECTED]` after successful login.

## 2. Windows PowerShell access to the course container

This machine was verified on 2026-11-16 using the locally available `csi201-cw1:latest` image, built from the supplied environment files, with Python 3.12.15. Local image names are not a substitute for the image/tag specified on Learning Mall. Use the examiner's specified image for assessment.

First change to the actual extracted `Codes` directory in PowerShell. Start the container shell:

```powershell
$codePath = (Get-Location).Path
docker run --rm -it --name cw1-run --mount "type=bind,source=$codePath,target=/code,readonly" -w /code --entrypoint /bin/sh csi201-cw1:latest
```

At the container's `#` prompt, run the server command from section 1. Keep that terminal open. In two new PowerShell terminals, run:

```powershell
docker exec -it cw1-run python3 client.py --server 127.0.0.1 --port 5000 --id alice --name Alice
docker exec -it cw1-run python3 client.py --server 127.0.0.1 --port 5000 --id bob --name Bob
```

`docker run` creates the container once; `docker exec` starts additional processes in that existing container. If the name is already in use, use the existing running container or choose a different unused name consistently. Do not create another container for every player.

All processes above share one container's loopback network, so no host port mapping is needed. `127.0.0.1` in a different container or on Windows refers to a different network namespace. Cross-container deployment requires a reachable bind address and appropriate networking; it is outside this documented setup.

To stop, type `quit` in each client, press Ctrl+C in the server terminal, then type `exit` at the shell prompt. `--rm` removes the stopped container; it does not delete the mounted source files.

## 3. Client command reference

Type these commands at the client's `>` prompt, not in PowerShell or the container shell.

| Command | Action |
| --- | --- |
| `help` | Show the command reference |
| `quizzes` | List public quiz metadata |
| `rooms` | List joinable waiting rooms |
| `create <quiz_id>` | Create a room and become its host |
| `join <room_id>` | Join a waiting room |
| `players` | Refresh participants, host, readiness, and scores |
| `ready` / `ready off` | Set or clear readiness |
| `start` | Ask to start; only the room host may do so |
| `answer <question_id> <A/B/C/D>` | Submit an answer for the named open question |
| `score` | Display the last server-confirmed scores |
| `status` | Display local identity, room, and phase |
| `leave` | Leave the current room |
| `quit` | Release identity/seat and close the client |

A complete two-player walkthrough:

1. Alice types `quizzes`, then `create network-basics`.
2. Note the returned room ID, such as `R1`; Bob types `rooms`, then `join R1`, using the actual ID.
3. Both type `players` and `ready`. Confirm both players are ready.
4. Alice, the creator/host, types `start`. Bob does not need to type it.
5. Each client receives the question, four options, question ID, points, and time limit. Submit before the deadline, for example `answer NET001 B`. A letter alone is not a command.
6. Wait for the result and next question. Repeat with each newly displayed ID. Correct answers are revealed only after closure.
7. After the final `[LEADERBOARD]`, type `leave` to return to the lobby or `quit` to exit. Finished rooms cannot restart.

## 4. Rules, validation, and assumptions

- Active user IDs are unique; duplicate login returns `DUPLICATE_USER` and leaves the original client connected. IDs must contain 1-64 printable characters with no surrounding whitespace. Names are trimmed, nonblank, and at most 64 printable characters; names may repeat.
- A player belongs to at most one room. The CLI requires leaving before creating or joining another. Only waiting rooms accept new players.
- The host can start only when at least two players are present and every current player is ready. These checks and the start reservation are synchronized.
- If the host leaves, the remaining user ID that sorts first becomes host. Empty rooms are deleted. Finished rooms remain non-joinable until their players leave.
- Each room owns separate question state, deadlines, answers, and scores. Questions follow bank order. The server uses a monotonic clock and closes each question at its deadline or after all remaining active players have answered.
- Only the first valid, current-question answer received before the deadline is accepted. Correct answers add that question's `points`; wrong or missing answers add zero. Duplicate, late, or stale submissions are rejected without changing an accepted answer.
- Rankings sort by descending score, then ascending user ID. Ranks are sequential. Disconnected players retain earned scores in the final leaderboard.
- The complete bank is validated before listening: UTF-8 JSON object, maximum 1,048,576 bytes, integer `schema_version=1`, required fields, array bounds, ID format/uniqueness, text limits, exact A/B/C/D options, answer, time limits, and points. Booleans/floats are not integer fields. An initial UTF-8 BOM is accepted. Extra members are ignored except extra option keys.
- Public catalogues expose quiz ID, title, description, and question count, not question text/options/answers. Open-question events omit the answer.
- Ctrl+C stops the server, closes connections, and stops/waits for match timers. Clients also exit on EOF, Ctrl+C, or remote closure, including while waiting for keyboard input.

## 5. Included files and question banks

| File/directory | Purpose |
| --- | --- |
| `server.py`, `protocol.py` | TCP sessions, worker threads, JSON Lines framing, sends, dispatch, and shutdown |
| `server_modules/question_bank.py` | Complete bank loading and typed question/quiz objects |
| `server_modules/lobby.py` | Identities, rooms, host/readiness rules, routing, and business cleanup |
| `server_modules/game_engine.py`, `scoring.py` | Per-room timing, answer acceptance, scoring, and ranking |
| `client.py`, `client_modules/` | CLI, connection/request matching, events, and synchronized local state |
| `questions.json` | Default development bank: two quizzes with five questions each |
| `questions_50.json` | Additional bank: five quizzes with ten questions each; a paired test depends on it |
| `PROTOCOL.md` | Implemented wire fields, events, error codes, locks, and lifecycle |
| `tests/` | Automated tests and their supporting peers/process tools |

The default bank contains Networking Fundamentals and Python Networking. It meets the requirement for at least two quizzes with at least five questions each.

The additional bank contains Geography, History, Natural Science, Literature and the Arts, and Mathematics and Logic. Content comparison on 2026-11-16 confirmed that it matches the file at the local path `CSI201_CW1_Docker_Env/CSI201_CW1_Docker_Env/questions_50.json`; only line endings differ. The publisher and original download source have not been independently verified. Do not describe it as an official or examiner-provided bank on this evidence alone.

The task sheet requires a valid submitted `questions.json` containing at least two quizzes with five questions per quiz (Submission, page 8). It does not require `questions_50.json`. We include this additional file as relevant test data for alternate-bank loading, not as a compulsory course asset or a known examiner test bank. Keep its existing name because the included paired test refers to that path; renaming it requires updating the test and this guide. The examiner may select another schema-valid bank using `--questions` (Normative question-bank input format, page 3).

In the Development Documentation, describe the default bank and validation in Data Design, and record the alternate-bank procedure and actual result in Verification and Validation. State that the alternate-bank check verifies startup, login, and catalogue metadata; it does not play all 50 questions. Cite the task sheet for the required schema and submission rules. Record the local file provenance accurately if discussing the additional data; do not attribute it to the examiner without source confirmation. This README is an operator guide and does not replace the required `Documentation/Development_Documentation.pdf`.

To select that bank, stop the server and relaunch:

```sh
python3 server.py --host 127.0.0.1 --port 5000 --questions questions_50.json
```

Only the selected file is loaded. There is no automatic fallback or combined bank. Clients keep the same launch commands and obtain the selected catalogue through `quizzes`.

## 6. Verification: what the 146 tests mean

The number is the count of Python unittest test methods in this project, not a coursework requirement or a count of manual actions. A method may perform multiple assertions/subcases. Module tests use controlled objects or scripted peers; the five paired-system methods launch the actual submitted server and client processes. These provide different kinds of evidence.

Run all tests from `Codes` inside the course container, before starting a manual server or after stopping it:

```sh
python3 -B -m unittest discover -s tests -v
```

The test harness starts and stops its own servers on available ports. The normal client never reads a bank; the test harness reads expected answers to check scores. See [tests/README.md](tests/README.md) for the per-file count, specific paired scenarios, and individual commands.

| Requirement | Relevant checks |
| --- | --- |
| Task 1: startup and bank validation | `test_question_bank.py`, `test_startup.py`, bank cases in `test_integration_regressions.py` |
| Task 2: identity and connection | `test_lobby.py`, `test_connection.py`, duplicate login in `test_paired_system.py` |
| Task 3: catalogue and rooms | `test_lobby.py` and the two-player paired workflow |
| Task 4: questions, timing, scores, leaderboard | `test_game_engine.py` and paired match/deadline scenarios |
| Task 5: at least ten clients and two independent rooms | Both ten-real-CLI-client methods in `test_paired_system.py` |
| Task 6: failure isolation and shutdown | Network/protocol/disconnect/client regressions and the paired malformed-input/SIGINT scenario |

Each verbose result ending in `ok` passed. The final successful summary is `Ran 146 tests ... OK` with process exit status 0. `FAIL` means an assertion failed; `ERROR` means a test could not complete; either produces a nonzero status and needs investigation.

Some failure-handling tests deliberately print `Response encoding failed`, `Broken pipe`, or `simulated business cleanup failure`. Those are injected conditions, not the test verdict. Read the corresponding `ok` and final summary. A test method with `error` or `failure` in its name is not itself a failed result.

For persistent paired transcripts, choose a writable directory in the container:

```sh
QUIZ_EVIDENCE_DIR=/tmp/quiz-evidence python3 -B -m unittest discover -s tests -p test_paired_system.py -v
```

Default runs use temporary files. Evidence output includes per-process transcripts, actual banks, and exit codes. Automated checks do not replace a manual demonstration, the required team video, or review of the final report.

## 7. Limitations and final packaging

- No passwords, TLS, database, reconnect/resume, or persistent results. Use a trusted course test network.
- Requests normally time out after five seconds. Timeout means the outcome is unknown, so state-changing requests are not retried automatically. Use `players`/`rooms` to refresh, or restart a disconnected client.
- JSON frames are limited to 64 KiB. Accepted sockets use a one-second operation timeout; idle reads keep waiting, while failed sends close the affected connection.
- No global connection quota or complete hostile-load protection is implemented. Tests cover specific scenarios, not all schedules or arbitrary loads.
- The CLI prints the time limit but has no continuously refreshed countdown. Only waiting rooms appear in `rooms`.
- Keep the test helper files and `questions_50.json` with the tests. `fake_server.py`, `cli_demo_server.py`, and `server_temp_test.py` are deliberate test peers, not alternative assessed entry points.

The final ZIP must contain `Codes/` and `Documentation/Development_Documentation.pdf` as sibling directories. Confirm the final archive name and video submission instructions on Learning Mall. Exclude Dockerfiles, Compose files, images, virtual environments, caches/`*.pyc`, IDE files, `.git`, old exercise folders, and obsolete `server_modules/tem_server.py`. Preserve `README.md`, `PROTOCOL.md`, the runtime modules, and all test dependencies.

Extract the assembled ZIP into a new directory and repeat the documented startup, paired manual workflow, and automated tests against that extracted copy. Open the final PDF and check the team video separately; successful code tests alone do not establish that those deliverables are complete.

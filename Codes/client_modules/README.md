# Client module interfaces

The assessed entry point is [client.py](../client.py). The client uses Python 3.12 standard-library modules and raw TCP; it does not open question-bank files.

| Module | Responsibility |
| --- | --- |
| `connection.py` | Socket lifecycle, JSON Lines framing, request/response matching, and event delivery |
| `state.py` | Synchronized identity, room, question, score, and leaderboard state |
| `cli.py` | Argument-independent client runner, terminal input, command parsing, and output |

`run_client()` creates `ClientState` and `Connection`. A request worker performs blocking connect/request calls. A separate input reader waits for terminal input while the CLI loop handles input, request results, and asynchronous events. One network reader updates state before publishing events. Snapshots are detached copies; the UI loop owns user-visible output.

Requests carry IDs, so an asynchronous event cannot be mistaken for a reply. State updates reject foreign-room events and stale question results. A timeout does not prove a request failed and does not trigger an automatic retry. Remote socket closure notifies the CLI even while standard input is idle.

See the self-contained [operation guide](../README.md), [protocol](../PROTOCOL.md), and [test guide](../tests/README.md). Test peers are described in the test guide; they do not replace the formal server or establish full-system correctness.

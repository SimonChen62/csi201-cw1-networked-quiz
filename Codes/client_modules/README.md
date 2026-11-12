# Client module ownership

The assessed client entry point is `../client.py`. The client uses only the Python 3.12 standard library and raw TCP. See [E's CLI guide](../../docs/E_client_guide.md) and the [D/E interface table](../../CW1_D与E接口确定表.md).

- `connection.py`: D, client socket and JSON-lines receive/send logic.
- `state.py`: D, local user, room and question state.
- `cli.py`: E, terminal input, menus and output.

E's `run_client()` constructs `ClientState` and `Connection`. A request worker calls the existing blocking `connect()/send_request()` methods; the UI loop reads `event_queue` and `get_snapshot()` while a separate input thread waits for keyboard input. The network reader updates state before publishing events. All user-facing output comes from the UI loop.

This branch includes E integration fixes in D-owned files: correlated error responses, pending-request cleanup, detached snapshots, stale question/room guards and shutdown notification. D's review is requested before merging. The business payloads in the interface table await B/C confirmation.

`tests/cli_demo_server.py` is a scripted single-client peer for development. A's echo client and this peer do not replace the real server or prove multi-room correctness.

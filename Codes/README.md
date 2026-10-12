# CSI201 CW1 Minimal Network Skeleton

This is the first A-owned network skeleton. It currently demonstrates:

- Python 3.12 Standard Library only
- raw TCP sockets
- one JSON object per line, terminated by `\\n`
- TCP fragmentation/coalescing handling through a receive buffer
- one thread per connected client
- duplicate active user ID rejection
- malformed message and unknown command responses
- `SERVER_READY` and Ctrl+C cleanup

Room management, quiz catalogue messages, tournament timing, scoring and the final `client.py` CLI workflow will be added through the B, C, D and E interfaces.

Run these commands from the `Codes/` directory.

## Run locally

```bash
python3 server.py --host 127.0.0.1 --port 5000 --questions questions.json
python3 tests/server_temp_test.py --server 127.0.0.1 --port 5000 --id zhangsan123 --name "Zhang San"
```

Inside the temporary `server_temp_test.py` client, type `ping` or `quit`.

## Run with Docker

```bash
docker compose up --build
```

In another terminal, run a client using the host-published port:

```bash
docker run --rm -it --network host cw1-server \
  python3 tests/server_temp_test.py --server 127.0.0.1 --port 5000 --id zhangsan123 --name "Zhang San"
```

If the image has not been tagged, build it first:

```bash
docker build -t cw1-server .
```

The Dockerfile is only a local development scaffold. The final archive must follow the coursework instruction and must not include a Dockerfile or Docker image.

# A network tests

`server_temp_test.py` is only a small manual client for testing A's server and protocol.
It is not the assessed `client.py`. D/E will create the final client later.

`test_network.py` is an automated test for A's Lab 4 TCP work. It starts the real
server on an ephemeral local port and checks the observable network behaviour:

- the `hello` and `ping` request/reply flow;
- one JSON message split across multiple `recv()` calls;
- multiple JSON messages received in one `recv()` call;
- duplicate active user IDs;
- malformed JSON and unknown commands;
- two clients using independent TCP connections.

Run it from `Codes/`:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

Run from the repository root with the `Codes/` path:

```bash
python Codes/tests/server_temp_test.py --id zhangsan123 --name "Zhang San"
```

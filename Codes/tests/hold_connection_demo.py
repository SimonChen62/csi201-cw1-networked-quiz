"""A's manual tool for observing TCP disconnects and server shutdown."""

import argparse
import socket


def main():
    parser = argparse.ArgumentParser(description="Keep one connection open for manual shutdown checks")
    parser.add_argument("--server", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    try:
        with socket.create_connection((args.server, args.port), timeout=5) as connection:
            # Limit connection setup to 5 seconds, then wait without an idle timeout.
            connection.settimeout(None)
            print("CONNECTED: keep this window open; Ctrl+C here disconnects this client.", flush=True)
            while True:
                chunk = connection.recv(1024)
                if not chunk:
                    print("SERVER_CLOSED: recv returned empty bytes.", flush=True)
                    return 0
                print(f"RECEIVED: {chunk!r}", flush=True)
    except KeyboardInterrupt:
        print("CLIENT_CLOSED: interrupted locally.", flush=True)
        return 0
    except OSError as exc:
        print(f"NETWORK_ERROR: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

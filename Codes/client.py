"""Command-line entry point for the paired quiz client."""

import argparse

from client_modules.cli import run_client


def main(argv=None):
    parser = argparse.ArgumentParser(description="Networked Quiz Tournament CLI client")
    parser.add_argument("--server", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--id", dest="user_id", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if not args.user_id.strip() or not args.name.strip():
        parser.error("--id and --name must not be empty")
    return run_client(args.server, args.port, args.user_id, args.name)


if __name__ == "__main__":
    raise SystemExit(main())


"""Command-line entry point for the paired quiz client."""

import argparse
import sys
from pathlib import Path

# Ensure that modules under the client_modules directory can be imported correctly regardless of where it is run from
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from client_modules.cli import run_client
except ImportError:
    # Compatible with direct run environments of some IDEs or test frameworks
    from cli import run_client


def main(argv=None):
    parser = argparse.ArgumentParser(description="Networked Quiz Tournament CLI client")
    parser.add_argument("--server", required=True, help="Server IP address")
    parser.add_argument("--port", type=int, required=True, help="Server TCP port")
    parser.add_argument("--id", dest="user_id", required=True, help="Unique user ID")
    parser.add_argument("--name", required=True, help="Display name")
    
    args = parser.parse_args(argv)
    
    # Argument validity check
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if not args.user_id.strip() or not args.name.strip():
        parser.error("--id and --name must not be empty")
        
    try:
        exit_code = run_client(args.server, args.port, args.user_id, args.name)
        return exit_code if isinstance(exit_code, int) else 0
        
    except KeyboardInterrupt:
        # Catch Ctrl+C and exit gracefully
        print("\n[!] Client interrupted by user (Ctrl+C). Disconnecting...")
        return 0
    except Exception as exc:
        # Catch other unhandled exceptions (such as rare low-level network crashes)
        print(f"\n[!] Fatal error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

import argparse
import sys


def main() -> int:
    from mcp_server.server import main as server_main

    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", default="stdio")
    parser.add_argument("--port", type=int, default=8001)
    args, _ = parser.parse_known_args()
    server_main(transport=args.transport, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())

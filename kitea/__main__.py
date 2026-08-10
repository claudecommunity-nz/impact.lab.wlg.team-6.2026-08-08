"""Entry point: python3 -m kitea [--host H] [--port N]"""

import argparse

from .server import run

parser = argparse.ArgumentParser(description="Kitea two-way channel server")
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=8146)
parser.add_argument("--workers", type=int, default=1)
args = parser.parse_args()
run(host=args.host, port=args.port, workers=args.workers)

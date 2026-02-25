
import argparse
import typing

from . import types
from . import blp_mcp_server

def parse_args():
  parser = argparse.ArgumentParser()
  parser.add_argument("--sse", action="store_true", help="Run an sse server instead of stdio")
  parser.add_argument("--host", type=str, default=None)
  parser.add_argument("--port", type=int, default=None)

  args = parser.parse_args()
  is_http = args.sse or args.host != None or args.port != None

  # Use streamable-http so the same URL supports both GET (SSE) and POST (JSON-RPC)
  transport = types.Transport.STREAMABLE_HTTP if is_http else types.Transport.STDIO
  host = args.host if args.host != None else "127.0.0.1"
  port = args.port if args.port != None else 8000
  return types.StartupArgs(transport=transport, host=host, port=port)

def main() -> None:
  args = parse_args()
  blp_mcp_server.serve(args)

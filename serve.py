#!/usr/bin/env python3
"""Serve agent-usage-status.json over localhost, gated by an API key.

Meant to sit behind a Cloudflare Tunnel (or any reverse proxy) -- binds to
127.0.0.1 only. Reads the API key from $API_KEY.

Usage: ./serve.py [--port PORT]
"""
import argparse
import hmac
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(HERE, "agent-usage-status.json")


class Handler(BaseHTTPRequestHandler):
    server_version = "agent-usage-widget/1.0"

    def _unauthorized(self):
        self.send_response(401)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _not_found(self):
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path != "/agent-usage-status.json":
            self._not_found()
            return

        api_key = os.environ.get("API_KEY", "")
        given = self.headers.get("X-Api-Key", "")
        if not api_key or not hmac.compare_digest(given, api_key):
            self._unauthorized()
            return

        try:
            with open(JSON_PATH, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            self._not_found()
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if not os.environ.get("API_KEY"):
        print("API_KEY environment variable is required", file=sys.stderr)
        return 1

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    sys.exit(main())

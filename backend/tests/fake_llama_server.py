#!/usr/bin/env python3
"""Minimal stand-in for llama.cpp's llama-server, used by the tests (OpenAI-style SSE streaming)."""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

port = int(sys.argv[sys.argv.index("--port") + 1])
model = sys.argv[sys.argv.index("-m") + 1]
print(f"fake llama-server loading {model}", flush=True)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(200, {"status": "ok"}) if self.path == "/health" else self._send(404, {})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/apply-template":
            return self._send(200, {"prompt": "<prompt>" + "|".join(m["content"] for m in req["messages"])})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        if self.path == "/v1/chat/completions":
            thinking = req.get("chat_template_kwargs", {}).get("enable_thinking")
            pieces = ["<think>", "hidden plan", "</think>", "Hello", " there", "!"] if not thinking else ["Hi"]
            for p in pieces:
                self.wfile.write(f"data: {json.dumps({'choices': [{'delta': {'content': p}}]})}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
        else:  # /completion
            for p, stop in (("continued", False), (" text", True)):
                self.wfile.write(f"data: {json.dumps({'content': p, 'stop': stop})}\n\n".encode())


ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()

"""A tiny local stand-in for an OpenAI-compatible chat-completions
endpoint (Groq/OpenAI/Together/etc. all share this shape) — used only for
real, over-the-wire integration verification of
llm/openai_compatible_provider.py's actual HTTP client code, since no
real third-party fallback-provider credentials are available in this
environment. Not a mock at the Python function level: this is a genuine
HTTP server on localhost that the provider's urllib client talks to for
real, matching the real request/response shape.

Usage: python scripts/fake_openai_compatible_server.py [port]
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # keep stdout clean; this is a throwaway test double

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        auth = self.headers.get("Authorization", "")

        if "test-fallback-key" not in auth:
            self._send(401, {"error": {"message": "invalid api key"}})
            return

        is_json_mode = (body.get("response_format") or {}).get("type") == "json_object"
        user_message = ""
        for m in body.get("messages", []):
            if m.get("role") == "user":
                user_message = m.get("content", "")

        if is_json_mode:
            content = json.dumps({"intent": "CASUAL"})
        else:
            content = (
                f"[FAKE FALLBACK PROVIDER] Real HTTP round trip succeeded. "
                f"model={body.get('model')} prompt_len={len(user_message)}"
            )

        self._send(200, {"choices": [{"message": {"role": "assistant", "content": content}}]})

    def _send(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"fake OpenAI-compatible server listening on http://127.0.0.1:{port}")
    server.serve_forever()

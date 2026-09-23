"""Ephemeral loopback HTTP mock with per-launch demo credentials."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading

from mock_server.fixtures import compare, lookup

MAX_BODY = 32_000


@contextmanager
def running_server(
    failure: str = "none", *, sources: dict[str, dict[str, str] | None] | None = None,
):
    if failure not in {"none", "expired", "unavailable"}:
        raise ValueError("Unknown mock failure mode")
    responses = None
    if sources is not None:
        if not isinstance(sources, dict):
            raise ValueError("Mock sources must be a dictionary.")
        responses = {}
        for case_id, source in sources.items():
            if not isinstance(case_id, str) or not case_id.strip() or len(case_id) > 8_000:
                raise ValueError("Mock source identifiers must be nonempty bounded strings.")
            if source is None:
                result = {"status": "no_hit", "source": None}
            else:
                if (
                    not isinstance(source, dict) or set(source) != {"title", "text", "location"}
                    or any(not isinstance(value, str) or not value.strip() for value in source.values())
                ):
                    raise ValueError("Mock sources require title, text and location strings.")
                result = {"status": "found", "source": {
                    **source, "id": case_id, "authority": "mock_fixture_only",
                }}
            if len(json.dumps({"mock": True, **result}).encode("utf-8")) > 64_000:
                raise ValueError("Mock source response exceeds the client size limit.")
            responses[case_id] = result
    bootstrap = secrets.token_urlsafe(24)
    token = secrets.token_urlsafe(24)
    events = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # Never log document contents, credentials or request bodies.

        def reply(self, status, body):
            payload = json.dumps({"mock": True, **body}).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            if (
                self.headers.get("Origin") is not None
                or self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}"
                or self.headers.get("Content-Type") != "application/json"
                or not secrets.compare_digest(self.headers.get("X-Demo-Key", ""), bootstrap)
            ):
                self.reply(403, {"error": "demo_access_denied"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.reply(400, {"error": "invalid_length"})
                return
            if not 0 < length <= MAX_BODY:
                self.reply(413, {"error": "body_limit"})
                return
            try:
                body = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeError):
                self.reply(400, {"error": "invalid_json"})
                return
            if not isinstance(body, dict):
                self.reply(400, {"error": "object_required"})
                return
            if self.path == "/session":
                if body != {"mode": "synthetic"}:
                    self.reply(400, {"error": "synthetic_mode_required"})
                    return
                events.append({"path": self.path, "result": "demo_session"})
                self.reply(200, {"token": token})
                return
            if (
                failure == "expired"
                or not secrets.compare_digest(
                    self.headers.get("Authorization", ""), f"Bearer {token}"
                )
            ):
                self.reply(401, {"error": "demo_session_expired"})
                return
            if self.path not in {"/precedents/search", "/slm/compare"}:
                self.reply(404, {"error": "unknown_route"})
                return
            if failure == "unavailable":
                self.reply(503, {"error": "demo_service_unavailable"})
                return
            expected = {"case_id"} if self.path.endswith("search") else {"case_id", "claim", "source_text"}
            if (
                set(body) != expected
                or any(not isinstance(value, str) or len(value) > 8_000 for value in body.values())
            ):
                self.reply(400, {"error": "invalid_fields"})
                return
            if self.path.endswith("search"):
                result = lookup(body["case_id"]) if responses is None else responses.get(
                    body["case_id"], {"status": "fixture_not_configured", "source": None},
                )
            elif responses is None:
                result = compare(**body)
            else:
                result = {
                    "status": "insufficient_basis",
                    "reason": "Custom lookup fixtures have no configured comparison; no model was run.",
                }
            events.append({"path": self.path, "result": result["status"]})
            self.reply(200, result)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", bootstrap, events
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

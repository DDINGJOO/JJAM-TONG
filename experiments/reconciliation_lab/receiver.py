"""Loopback-only webhook receiver for a public, synthetic experiment."""
import hashlib
import hmac
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .reconcile import IntakeRejected

MAX_BODY = 64 * 1024
FIXTURE_KEY = b"public-fixture-only-not-a-webhook-credential"


def accept(store, body, headers, repository, ref, secret):
    if len(body) > MAX_BODY:
        raise IntakeRejected("payload_too_large", 413)
    signature = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    supplied = headers.get("X-Hub-Signature-256", "")
    if not re.fullmatch(r"sha256=[0-9a-f]{64}", supplied) or not hmac.compare_digest(signature, supplied):
        raise IntakeRejected("invalid_signature", 401)
    delivery = headers.get("X-GitHub-Delivery", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", delivery):
        raise IntakeRejected("invalid_delivery_id", 400)
    if headers.get("X-GitHub-Event") != "push":
        return "ignored_event"
    try:
        payload = json.loads(body)
        if payload["repository"]["full_name"] != repository or payload["ref"] != ref:
            return "ignored_target"
    except (ValueError, KeyError, TypeError):
        raise IntakeRejected("invalid_payload", 400) from None
    return store.request(delivery, hashlib.sha256(body).hexdigest())


def signed(body, delivery):
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(FIXTURE_KEY, body, hashlib.sha256).hexdigest(),
            "X-GitHub-Event": "push", "X-GitHub-Delivery": delivery}


def server(store_factory, repository, ref="refs/heads/main", secret=FIXTURE_KEY):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.connection.settimeout(5)
            if self.path != "/webhook":
                self.send_error(404)
                return
            length = self.headers.get("Content-Length", "")
            if not length.isdigit() or int(length) > MAX_BODY:
                self.send_error(413)
                self.close_connection = True
                return
            body = self.rfile.read(int(length))
            store = store_factory()
            try:
                result = accept(store, body, self.headers, repository, ref, secret)
                status = 202
            except IntakeRejected as error:
                status, result = error.status, str(error)
            finally:
                store.close()
            raw = json.dumps({"result": result}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)

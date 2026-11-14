"""Loopback-only, same-origin HTTP consumer; deliberately not a production server."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit

import psycopg

from tools.evidence_store.contracts import EvidenceTimeout, VersionMismatch
from .service import MissingHistory

STATIC = Path(__file__).with_name("static")
ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
          "/demo": ("demo.html", "text/html; charset=utf-8"),
          "/prototype.css": ("prototype.css", "text/css; charset=utf-8"),
          "/prototype.js": ("prototype.js", "text/javascript; charset=utf-8"),
          "/platform.js": ("platform.js", "text/javascript; charset=utf-8"),
          "/demo-entry.js": ("demo-entry.js", "text/javascript; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/app.css": ("app.css", "text/css; charset=utf-8")}
ROUTES = {"/api/context": "context", "/api/snapshots": "snapshots", "/api/snapshot": "snapshot",
          "/api/methods": "methods", "/api/graph": "graph", "/api/traces": "traces", "/api/trace": "trace"}


class WorkspaceServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, workspace, port=28740, *, assets=None, routes=None, inline_styles=()):
        self.workspace = workspace
        self.assets = ASSETS if assets is None else assets
        self.routes = ROUTES if routes is None else routes
        self.inline_styles = frozenset(inline_styles)
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(("127.0.0.1", port), Handler)
        self.authorities = {"127.0.0.1:" + str(self.server_port), "localhost:" + str(self.server_port)}

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.settimeout(1)
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "JJAM-TONG-local"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_args):
        # Request URLs can contain identifiers; do not log input or local paths.
        pass

    def _send(self, code, body, content_type="application/json; charset=utf-8", demo=False, inline_style=False):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        # The preserved synthetic tour positions its cards with style attributes.
        # It has no network connection permission. Keep the live consumer strict.
        style_policy = "'self' 'unsafe-inline'" if demo or inline_style else "'self'"
        connect_policy = "'none'" if demo else "'self'"
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src "
                         + style_policy + "; connect-src " + connect_policy +
                         "; img-src 'self' data:; frame-ancestors 'none'; "
                         "base-uri 'none'; form-action 'none'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, code, data):
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
        if len(body) > 4 * 1024 * 1024:
            return self._error(413, "RESPONSE_BUDGET", "조회 결과가 화면 응답 상한을 넘었어요. 범위를 줄여주세요.")
        self._send(code, body)

    def _error(self, code, kind, message):
        self._json(code, {"error": kind, "message": message})

    def do_GET(self):
        authority = self.headers.get("Host", "").lower()
        origins = {"http://" + value for value in self.server.authorities}
        if (authority not in self.server.authorities or len(self.headers.get_all("Host", [])) != 1
                or self.headers.get("Origin", "http://" + authority) not in origins
                or self.headers.get("Sec-Fetch-Site") == "cross-site"):
            return self._error(403, "LOCAL_ORIGIN_REQUIRED", "이 화면의 로컬 주소에서 직접 조회해주세요.")
        try:
            if len(self.path) > 8192:
                raise ValueError("URL too long")
            url = urlsplit(self.path)
            if url.scheme or url.netloc or url.fragment:
                raise ValueError("Origin-form request required")
            params = parse_qs(url.query, keep_blank_values=True, max_num_fields=20)
            if any(len(values) != 1 for values in params.values()):
                raise ValueError("Duplicate query field")
            params = {key: values[0] for key, values in params.items()}
            if url.path in self.server.assets and not params:
                filename, content_type = self.server.assets[url.path]
                return self._send(200, (STATIC / filename).read_bytes(), content_type,
                                  demo=url.path == "/demo", inline_style=url.path in self.server.inline_styles)
            if url.path not in self.server.routes:
                return self._error(404, "NOT_FOUND", "조회 경로를 찾을 수 없어요.")
            result = getattr(self.server.workspace, self.server.routes[url.path])(params)
            self._json(200, result)
        except VersionMismatch:
            self._error(409, "VERSION_MISMATCH", "선택한 분석 해시와 저장된 근거가 달라요. 다른 버전으로 대체하지 않았어요.")
        except MissingHistory:
            self._error(404, "HISTORY_NOT_COLLECTED", "이 분석 이력이 없어요. 다른 빌드로 대체하지 않았어요.")
        except (EvidenceTimeout, psycopg.errors.QueryCanceled):
            self._error(504, "TIME_BUDGET", "DB 조회 시간 상한에 도달했어요. 범위를 줄이거나 다시 조회해주세요.")
        except psycopg.Error:
            self._error(503, "DATABASE_UNAVAILABLE", "DB에 연결하지 못했어요. 로컬 DB 상태를 확인해주세요.")
        except (ValueError, KeyError, TypeError, AttributeError):
            self._error(400, "INVALID_QUERY", "조회 조건을 확인해주세요. 정확한 분석·메서드 식별자가 필요해요.")
        except OSError:
            self._error(503, "LOCAL_RESOURCE_UNAVAILABLE", "로컬 화면 파일을 읽을 수 없어요.")

    def _read_only(self):
        self.close_connection = True
        self._error(405, "READ_ONLY", "이 로컬 화면은 GET 조회만 지원해요.")

    do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = _read_only

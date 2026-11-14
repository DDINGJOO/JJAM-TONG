"""Serve a collected local source snapshot without opening the target application."""
import argparse
from pathlib import Path
from tools.evidence_web.server import ASSETS, WorkspaceServer
from .workspace import SourceWorkspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--port", default=28742, type=int)
    args = parser.parse_args()
    assets = {k: v for k, v in ASSETS.items() if k in ("/demo", "/demo-entry.js", "/prototype.js", "/prototype.css")}
    assets.update({"/": ("service.html", "text/html; charset=utf-8"),
                   "/service-analysis": ("service.html", "text/html; charset=utf-8"),
                   "/service.js": ("service.js", "text/javascript; charset=utf-8"),
                   "/service.css": ("service.css", "text/css; charset=utf-8")})
    routes = {"/api/service/" + name: name for name in ("summary", "endpoints", "methods", "method", "graph")}
    workspace = SourceWorkspace(args.snapshot)
    with WorkspaceServer(workspace, args.port, assets=assets, routes=routes,
                         inline_styles=("/", "/service-analysis")) as server:
        print("Source analysis: http://127.0.0.1:%s/service-analysis" % server.server_port, flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()

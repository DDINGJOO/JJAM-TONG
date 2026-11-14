"""Immutable source snapshot queries. No repository or application operations."""
from collections import defaultdict, deque
import json
from pathlib import Path


class SourceWorkspace:
    def __init__(self, filename):
        path = Path(filename)
        if path.stat().st_size > 256 * 1024 * 1024:
            raise ValueError("Source snapshot exceeds local input budget")
        self.data = json.loads(path.read_text(encoding="utf-8"))
        if self.data.get("schema") != "jjamtong.service-source.v1":
            raise ValueError("Unsupported source snapshot schema")
        self.index = {m["id"]: m for m in self.data["methods"]}
        if len(self.index) != len(self.data["methods"]):
            raise ValueError("Duplicate source method identity")
        self.outgoing = defaultdict(list)
        self.calls_by_source = defaultdict(list)
        for call in self.data.get("calls", []):
            if call["source"] not in self.index:
                raise ValueError("Dangling callsite source")
            self.calls_by_source[call["source"]].append(call)
        incoming, outgoing = defaultdict(set), defaultdict(set)
        for edge in self.data["edges"]:
            if edge["source"] not in self.index or edge["target"] not in self.index:
                raise ValueError("Dangling source edge")
            self.outgoing[edge["source"]].append(edge)
            incoming[edge["target"]].add(edge["source"])
            outgoing[edge["source"]].add(edge["target"])
        self.handlers = {r["handlerId"] for r in self.data["endpoints"] if r.get("handlerId")}
        for m in self.index.values():
            m["incoming"], m["outgoing"] = len(incoming[m["id"]]), len(outgoing[m["id"]])
            reasons = list(m.get("noiseReasons", []))
            if m["kind"] == "constructor" and "constructor" not in reasons:
                reasons.append("constructor")
            if not m["incoming"] and not m["outgoing"] and m["id"] not in self.handlers:
                reasons.append("isolated-non-route")
            m["noiseReasons"] = reasons
        self.methods_ordered = sorted(self.index.values(), key=lambda m: (m["className"], m["name"], m["signature"], m["id"]))
        self.routes_ordered = sorted(self.data["endpoints"], key=lambda r: (r["module"], r["path"], r["httpMethod"], r["id"]))

    @staticmethod
    def _params(params, allowed):
        if set(params) - set(allowed):
            raise ValueError("Unsupported query field")
        if any(not isinstance(v, str) or len(v) > 1500 for v in params.values()):
            raise ValueError("Invalid query string")

    @staticmethod
    def _number(params, name, default, low, high):
        value = params.get(name, str(default))
        if not value.isascii() or not value.isdigit() or not low <= int(value) <= high:
            raise ValueError("Invalid bounded integer")
        return int(value)

    def summary(self, params):
        self._params(params, ())
        result = {k: self.data[k] for k in ("schema", "service", "metrics", "modules", "limitations")}
        result["provenance"] = self.data.get("provenance", {})
        failures = self.data.get("fileDiagnostics", [])
        result["fileDiagnostics"] = failures[:100]
        result["fileDiagnosticCount"] = len(failures)
        return result

    def _page(self, params, methods):
        self._params(params, ("module", "q", "offset", "limit", "focus", "include_private") if methods else ("module", "q", "offset", "limit"))
        offset = self._number(params, "offset", 0, 0, 1000000)
        limit = self._number(params, "limit", 80, 1, 200)
        module, query = params.get("module", ""), params.get("q", "").casefold().strip()
        if module and module not in {m["id"] for m in self.data["modules"]}:
            raise ValueError("Unknown module")
        items = self.methods_ordered if methods else self.routes_ordered
        fields = ("className", "name", "signature", "path") if methods else ("path", "httpMethod", "controller", "module")
        items = [m for m in items if (not module or m["module"] == module) and (not query or query in " ".join(str(m.get(k, "")) for k in fields).casefold())]
        hidden = 0
        if methods:
            focus = params.get("focus", "connected")
            private = params.get("include_private", "true")
            if focus not in ("connected", "all") or private not in ("true", "false"):
                raise ValueError("Unknown method filter")
            before = len(items)
            items = [m for m in items if (private == "true" or m.get("visibility") != "private") and
                     (focus == "all" or m["id"] in self.handlers or not m.get("noiseReasons"))]
            hidden = before - len(items)
        return {"items": items[offset:offset + limit], "total": len(items), "hiddenCount": hidden,
                "offset": offset, "limit": limit, "hasMore": offset + limit < len(items)}

    def endpoints(self, params):
        return self._page(params, False)

    def methods(self, params):
        return self._page(params, True)

    def method(self, params):
        self._params(params, ("id",))
        method = self.index[params["id"]]
        calls = self.calls_by_source[method["id"]]
        return {"method": method, "diagnostics": self.data.get("diagnostics", {}).get(method["id"], []),
                "calls": calls[:200], "callCount": len(calls), "callsTruncated": len(calls) > 200}

    def graph(self, params):
        self._params(params, ("method_id", "depth", "nodes", "edges"))
        root = params["method_id"]
        if root not in self.index:
            raise KeyError(root)
        depth = self._number(params, "depth", 4, 0, 12)
        node_limit = self._number(params, "nodes", 80, 1, 200)
        edge_limit = self._number(params, "edges", 200, 1, 600)
        visited, queue, edges, truncated = {root}, deque([(root, 0)]), [], False
        while queue:
            mid, level = queue.popleft()
            candidates = self.outgoing[mid]
            if level >= depth:
                truncated |= bool(candidates)
                continue
            for edge in candidates:
                target = edge["target"]
                if len(edges) >= edge_limit or target not in visited and len(visited) >= node_limit:
                    truncated = True
                    continue
                edges.append(edge)
                if target not in visited:
                    visited.add(target)
                    queue.append((target, level + 1))
        diagnostics = defaultdict(int)
        for mid in visited:
            for d in self.data.get("diagnostics", {}).get(mid, []):
                diagnostics[(d["code"], d["message"])] += d.get("count", 1)
        reasons = [{"code": "DISPLAY_LIMIT", "message": "깊이·노드·연결 표시 상한으로 일부 후보를 생략했습니다."}] if truncated else []
        diags = [{"code": code, "count": count, "message": message} for (code, message), count in sorted(diagnostics.items())]
        boundaries = [call for mid in sorted(visited) for call in self.calls_by_source[mid]
                      if call["resolution"] != "SOURCE_DECLARATION"]
        if len(boundaries) > 200:
            reasons.append({"code": "CALLSITE_LIMIT", "message": "미해결·외부 호출 위치는 처음 200개를 표시합니다."})
        return {"rootId": root, "methods": [self.index[mid] for mid in sorted(visited)], "edges": edges,
                "status": "PARTIAL" if truncated or diags or self.data["metrics"].get("failedFiles") else "STATIC_CANDIDATES",
                "reasons": reasons, "counts": {"nodes": len(visited), "edges": len(edges)}, "diagnostics": diags,
                "boundaries": boundaries[:200], "boundaryCount": len(boundaries)}

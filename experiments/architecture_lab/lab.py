"""Executable ingestion experiments, using only the Python standard library.

This is a synthetic adapter and a local SQLite implementation. It is not a
GitHub client, code analyzer, distributed broker, or production platform.
"""
import argparse
import copy
import hashlib
import hmac
import json
import platform
import sqlite3
import subprocess
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
VARIANTS = ("poll", "events", "hybrid")
FIXTURE_KEY = b"public-synthetic-webhook-key-not-a-credential"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class SourceUnavailable(Exception):
    pass


class InjectedCrash(Exception):
    pass


class Source:
    """Replaceable source port; pagination failures happen before publication."""

    def __init__(self, records):
        self.records = {r["key"]: copy.deepcopy(r) for r in records}
        self.available = True
        self.fail_page = None
        self.calls = Counter()

    def scan(self):
        self.calls["scans"] += 1
        if not self.available:
            raise SourceUnavailable("synthetic source unavailable")
        ordered = sorted(self.records.values(), key=lambda r: r["key"])
        complete = []
        for offset in range(0, len(ordered), 2):
            page = offset // 2 + 1
            self.calls["pages"] += 1
            if page == self.fail_page:
                raise SourceUnavailable("incomplete synthetic pagination")
            complete.extend(copy.deepcopy(ordered[offset:offset + 2]))
        return complete

    def change(self, key, patch, tick):
        record = copy.deepcopy(self.records[key])
        record.update(patch)
        record["revision"] = self.records[key]["revision"] + 1
        record["event_at"] = tick
        self.records[key] = record
        return copy.deepcopy(record)


def delivery(record, delivery_id):
    body = {"delivery_id": delivery_id, "record": record}
    signature = hmac.new(FIXTURE_KEY, canonical(body).encode(), hashlib.sha256).hexdigest()
    return dict(body, signature=signature)


class Store:
    """Immutable evidence revisions plus a transactional durable inbox.

    Revision numbers are synthetic source sequence numbers, never commit SHAs.
    No deletion is inferred from absence in a scan; tombstones are explicit.
    """

    def __init__(self, path):
        self.db = sqlite3.connect(str(path))
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS facts (
                scope TEXT NOT NULL, source TEXT NOT NULL, object_key TEXT NOT NULL,
                revision INTEGER NOT NULL, event_at INTEGER NOT NULL,
                recorded_at INTEGER NOT NULL, body TEXT NOT NULL,
                PRIMARY KEY (scope, source, object_key, revision)
            );
            CREATE TABLE IF NOT EXISTS inbox (
                delivery_id TEXT PRIMARY KEY, body TEXT NOT NULL,
                received_at INTEGER NOT NULL, processed_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS status (
                name TEXT PRIMARY KEY, value INTEGER NOT NULL
            );
        """)

    def close(self):
        self.db.close()

    def _project(self, record, tick):
        identity = (record["scope"], record["source"], record["key"], record["revision"])
        old = self.db.execute(
            "SELECT body FROM facts WHERE scope=? AND source=? AND object_key=? AND revision=?",
            identity,
        ).fetchone()
        body = canonical(record)
        if old:
            if old[0] != body:
                raise ValueError("conflicting evidence at the same source revision")
            return False
        self.db.execute("INSERT INTO facts VALUES (?,?,?,?,?,?,?)",
                        identity + (record["event_at"], tick, body))
        return True

    def snapshot(self, records, tick):
        with self.db:
            for record in records:
                self._project(record, tick)
            self.db.execute("INSERT OR REPLACE INTO status VALUES ('last_scan_success',?)", (tick,))

    def enqueue(self, message, tick):
        body = canonical(message)
        with self.db:
            old = self.db.execute("SELECT body FROM inbox WHERE delivery_id=?",
                                  (message["delivery_id"],)).fetchone()
            if old and old[0] != body:
                raise ValueError("conflicting payload for an existing delivery")
            self.db.execute("INSERT OR IGNORE INTO inbox VALUES (?,?,?,NULL)",
                            (message["delivery_id"], body, tick))

    def recover(self, tick, fault=None):
        pending = self.db.execute(
            "SELECT delivery_id,body FROM inbox WHERE processed_at IS NULL ORDER BY received_at,delivery_id"
        ).fetchall()
        for delivery_id, body in pending:
            with self.db:
                self._project(json.loads(body)["record"], tick)
                if fault == "mid_projection":
                    raise InjectedCrash("after projection write, before commit")
                self.db.execute("UPDATE inbox SET processed_at=? WHERE delivery_id=?", (tick, delivery_id))

    def view(self, permitted_scopes, event_before, known_before):
        latest = {}
        for scope, source, key, revision, recorded_at, body in self.db.execute(
            "SELECT scope,source,object_key,revision,recorded_at,body FROM facts WHERE event_at<=? AND recorded_at<=?",
            (event_before, known_before),
        ):
            if scope not in permitted_scopes:
                continue
            identity = (scope, source, key)
            if identity not in latest or latest[identity]["revision"] < revision:
                latest[identity] = json.loads(body)
                latest[identity]["recorded_at"] = recorded_at
        # The lab's keys are namespaced and globally unique within its fixture.
        # A production API must retain scope/source in externally visible identity.
        visible = {}
        for record in latest.values():
            if record.get("deleted", False):
                continue
            if record["key"] in visible:
                raise ValueError("fixture key collision across source/scope; no implicit merge")
            visible[record["key"]] = record
        return visible

    def stats(self):
        return {
            "evidence_revisions": self.db.execute("SELECT COUNT(*) FROM facts").fetchone()[0],
            "inbox_rows": self.db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0],
            "pending_deliveries": self.db.execute("SELECT COUNT(*) FROM inbox WHERE processed_at IS NULL").fetchone()[0],
            "last_scan_success": self.db.execute("SELECT value FROM status WHERE name='last_scan_success'").fetchone()[0],
        }


class Engine:
    def __init__(self, variant, source, path, interval=5):
        if variant not in VARIANTS:
            raise ValueError(variant)
        self.variant, self.source, self.path = variant, source, Path(path)
        self.interval = interval
        self.store = Store(path)
        self.tick = 0
        self.permitted_scopes = {"demo"}
        self.collection_scopes = {"demo"}
        self.counts = Counter()

    def poll(self):
        if not self.collection_scopes:
            self.counts["collection_denied"] += 1
            return False
        try:
            records = self.source.scan()
        except SourceUnavailable:
            self.counts["scan_failures"] += 1
            return False
        self.store.snapshot([r for r in records if r["scope"] in self.collection_scopes], self.tick)
        return True

    def receive(self, message, fault=None):
        if self.variant == "poll":
            return "ignored"
        body = {k: v for k, v in message.items() if k != "signature"}
        expected = hmac.new(FIXTURE_KEY, canonical(body).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, message.get("signature", "")) or body["record"]["scope"] not in self.collection_scopes:
            self.counts["rejected_events"] += 1
            return "rejected"
        self.counts["received_events"] += 1
        self.store.enqueue(message, self.tick)
        if fault == "after_inbox":
            raise InjectedCrash("after durable receipt, before processing")
        self.store.recover(self.tick, fault)
        return "processed"

    def advance(self, ticks):
        for _ in range(ticks):
            self.tick += 1
            if self.variant in ("poll", "hybrid") and self.tick % self.interval == 0:
                self.poll()

    def restart(self):
        self.store.close()
        self.store = Store(self.path)
        if self.collection_scopes:
            self.store.recover(self.tick)
        self.counts["restarts"] += 1

    def view(self, event_before=None, known_before=None):
        return self.store.view(self.permitted_scopes,
                               self.tick if event_before is None else event_before,
                               self.tick if known_before is None else known_before)

    def inspect_request(self, trace_key):
        visible = self.view()
        trace = visible.get(trace_key)
        if trace is None:
            return {"status": "unavailable"}
        context = trace["payload"]
        code = visible.get(context["code_key"])
        deploy = visible.get(context["deployment_key"])
        if not code or not deploy:
            return {"status": "incomplete"}
        for evidence in (code, deploy):
            if any(evidence["payload"][k] != context[k] for k in ("build", "artifact")):
                return {"status": "mismatch"}
        if context["method"] not in code["payload"]["methods"]:
            return {"status": "mismatch"}
        return {"status": "ok", "build": context["build"], "artifact": context["artifact"],
                "method": context["method"], "code_revision": code["revision"]}

    def stats(self):
        return dict(self.store.stats(), source=dict(self.source.calls), engine=dict(self.counts))


def matches(want, view):
    for key, expected in want.items():
        actual = view.get(key)
        if expected is None:
            if actual is not None:
                return False
        elif actual is None or any(actual["payload"].get(k) != v for k, v in expected.items()):
            return False
    return True


def subset(want, actual):
    return all(actual.get(k) == v for k, v in want.items())


def run_case(case, variant, directory):
    records = json.loads((HERE / "fixtures/base.json").read_text())
    source = Source(records)
    engine = Engine(variant, source, directory / "state.sqlite")
    assert engine.poll(), "common bootstrap must succeed"
    checkpoints, saved = [], {}
    try:
        for index, op in enumerate(case["operations"]):
            action = op["op"]
            if action == "advance":
                engine.advance(op["ticks"])
            elif action == "change":
                record = source.change(op["key"], op["patch"], op.get("event_at", engine.tick))
                message = delivery(record, op.get("delivery", str(index)))
                saved[op.get("save", str(index))] = message
                if op.get("emit", True):
                    try:
                        engine.receive(message, op.get("fault"))
                    except InjectedCrash:
                        assert op.get("fault"), "unexpected crash"
            elif action == "redeliver":
                engine.receive(saved[op["saved"]])
            elif action == "availability":
                source.available = op["available"]
            elif action == "partial":
                source.fail_page = op["page"]
            elif action == "restart":
                engine.restart()
            elif action == "revoke":
                engine.permitted_scopes.clear()
            elif action == "disconnect":
                engine.collection_scopes.clear()
            elif action == "forge":
                message = delivery(source.records["catalog/api"], "forged")
                message["record"] = dict(message["record"], revision=999,
                                         payload={"owner": "attacker"})
                engine.receive(message)
            elif action == "check":
                visible = engine.view(op.get("event_before"), op.get("known_before"))
                assert matches(op.get("must", {}), visible), (case["id"], variant, "safety oracle")
                if not engine.permitted_scopes:
                    assert visible == {}, "revocation exposed cached evidence"
                request = engine.inspect_request(op["request"]) if "request" in op else {}
                assert subset(op.get("must_request", {}), request), (case["id"], variant, request)
                keys = set(op.get("want", {})) | set(op.get("must", {}))
                checkpoints.append({"tick": engine.tick, "event_before": op.get("event_before", engine.tick),
                                    "known_before": op.get("known_before", engine.tick),
                                    "target_met": matches(op.get("want", {}), visible),
                                    "expected": op.get("want", {}), "safety_expected": op.get("must", {}),
                                    "observed": {k: visible.get(k) for k in sorted(keys)},
                                    "visible_keys": sorted(visible), "request": request})
            else:
                raise ValueError(action)
        assert checkpoints, "every experiment requires an independent checkpoint"
        return {"scenario": case["id"], "variant": variant, "bdd": case["bdd"],
                "safety_oracles_passed": True, "checkpoints": checkpoints, "stats": engine.stats()}
    finally:
        engine.store.close()


def workload(variant, count, directory):
    source = Source(json.loads((HERE / "fixtures/base.json").read_text()))
    engine = Engine(variant, source, directory / "state.sqlite")
    assert engine.poll()
    started = time.perf_counter()
    try:
        for i in range(1, count + 1):
            engine.advance(1)
            record = source.change("catalog/api", {"payload": {"owner": "team-" + str(i)}}, engine.tick)
            engine.receive(delivery(record, "work-" + str(i)))
        # A common final scan/recovery budget, not a hidden event-only fallback.
        engine.advance(engine.interval)
        elapsed = time.perf_counter() - started
        assert engine.view()["catalog/api"]["payload"]["owner"] == "team-" + str(count)
        result = dict(engine.stats(), elapsed_seconds=elapsed)
    finally:
        engine.store.close()
    result["sqlite_bytes"] = (directory / "state.sqlite").stat().st_size
    return result


def render_report(result):
    lines = ["# 자동 갱신 구조 비교 실험 결과", "",
             "합성 adapter + 동일 SQLite 저장소 + 단일 Python 프로세스에서 수행한 갱신 전략 실험이다.",
             "실제 GitHub·OTel·AWS·Backstage 연동, 분산 성능, 운영 비용의 검증 결과로 해석하지 않는다.", "",
             "`일치`는 해당 체크포인트에서 독립 기대값과 일치했음을, `지연/누락`은 갱신 목표 미달을 뜻한다.",
             "안전성 검증 실패는 프로그램을 실패시키며 목표 미달을 숨기지 않는다. 보편적인 우승자를 정하지 않는다.", "",
             "| 시나리오 | 주기적 조회 | 이벤트 | 혼합 |", "| --- | --- | --- | --- |"]
    for case in result["scenarios"]:
        cells = []
        for variant in VARIANTS:
            row = next(r for r in result["runs"] if r["scenario"] == case["id"] and r["variant"] == variant)
            cells.append(" / ".join("일치" if c["target_met"] else "지연/누락" for c in row["checkpoints"]))
        lines.append("| " + case["id"] + " " + case["name"] + " | " + " | ".join(cells) + " |")
    lines += ["", "## 합성 변경 부하의 관측값", "",
              "동일 건수의 변경을 전달하고 동일한 마지막 갱신 예산을 준다. 전체 입력은 JSON에 있다.",
              "로컬 실행 시간은 참고값이며 시스템 성능 순위·클라우드 요금의 근거로 사용하지 않는다.", "",
              "| 방식 | source 조회/페이지 | 저장한 근거 revision | inbox 행 | SQLite bytes | 실행 초 |",
              "| --- | --- | --- | --- | --- | --- |"]
    for variant in VARIANTS:
        row = result["workload"][variant]
        lines.append("| {} | {}/{} | {} | {} | {} | {:.6f} |".format(
            variant, row["source"]["scans"], row["source"]["pages"], row["evidence_revisions"],
            row["inbox_rows"], row["sqlite_bytes"], row["elapsed_seconds"]))
    lines += ["", "재현 명령·측정 경계·후속 비교 축은 [실험 설계](ARCHITECTURE-EXPERIMENTS.md)에 있다.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("results/architecture-lab"))
    parser.add_argument("--changes", type=int, default=200)
    args = parser.parse_args()
    if not __debug__:
        parser.error("Run without -O: this experiment requires assertion oracles")
    if args.changes < 1:
        parser.error("--changes must be positive")
    cases = json.loads((HERE / "fixtures/scenarios.json").read_text())
    runs, loads = [], {}
    with tempfile.TemporaryDirectory(prefix="jjamtong-architecture-") as temporary:
        root = Path(temporary)
        for case in cases:
            for variant in VARIANTS:
                directory = root / (case["id"] + "-" + variant)
                directory.mkdir()
                runs.append(run_case(case, variant, directory))
        for variant in VARIANTS:
            directory = root / ("work-" + variant)
            directory.mkdir()
            loads[variant] = workload(variant, args.changes, directory)
    inputs = [HERE / "lab.py", HERE / "test_lab.py", *sorted((HERE / "fixtures").glob("*.json"))]
    evidence = {str(p.relative_to(HERE)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    git = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
    result = {"schema": "jjamtong-experiment-v1", "created_at": datetime.now(timezone.utc).isoformat(),
              "environment": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
                              "system": platform.system(), "machine": platform.machine()},
              "base_commit": git.stdout.strip(), "input_sha256": evidence, "changes": args.changes,
              "configuration": {"poll_interval_ticks": 5, "source_page_size": 2, "timing_samples": 1},
              "limitations": ["synthetic sources", "single process", "shared SQLite implementation",
                              "no real analyzer or cloud", "no production benchmark", "no actual validity interval inference"],
              "scenarios": [{k: c[k] for k in ("id", "name", "bdd")} for c in cases],
              "runs": runs, "workload": loads}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "run.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    (args.output / "RESULTS.md").write_text(render_report(result))
    print(json.dumps({"scenario_variant_runs": len(runs), "safety_oracles": "passed",
                      "checkpoint_target_misses": sum(not c["target_met"] for r in runs for c in r["checkpoints"]),
                      "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()

"""Finite experiments: real local Git, loopback delivery, optional public GETs."""
import argparse
import hashlib
import json
import os
import platform
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .adapters import API_VERSION, GitHub, LocalGit, settings
from .fixtures import Repository
from .receiver import server, signed
from .reconcile import Store, work

HERE = Path(__file__).resolve().parent
STRATEGIES = ("poll", "hints", "hybrid")
BOUNDARIES = ("in_process", "subprocess")


def run_case(strategy, boundary):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repo = Repository(root / "source")
        config = settings()
        identity = LocalGit(repo.path, "fixture/community").source
        database = root / "work.sqlite"
        store = Store(database, identity, config)
        receiver = server(lambda: Store(database, identity, config), "fixture/community")
        thread = threading.Thread(target=receiver.serve_forever, daemon=True)
        thread.start()
        calls, builds, results, checkpoints = Counter(), 0, [], []
        started = time.perf_counter()

        def notify(delivery, after):
            body = json.dumps({"repository": {"full_name": "fixture/community"},
                               "ref": "refs/heads/main", "after": after}).encode()
            request = urllib.request.Request("http://127.0.0.1:%d/webhook" % receiver.server_port,
                                             data=body, headers=signed(body, delivery))
            with urllib.request.urlopen(request, timeout=5) as response:
                assert response.status == 202

        def drain(now):
            nonlocal builds
            if boundary == "in_process":
                result = work(store, LocalGit(repo.path, "fixture/community"), now)
            else:
                child = subprocess.run([sys.executable, "-m", "experiments.reconciliation_lab.worker",
                                        "--database", str(database), "--git", str(repo.path), "--now", str(now)],
                                       capture_output=True, text=True, timeout=20, check=True)
                result = json.loads(child.stdout)
            assert result["status"] in ("published", "idle"), result
            calls.update(result["calls"])
            builds += result.get("index_builds", 0)
            results.append(result["status"])

        def checkpoint(name, expected):
            current = store.current()
            assert current is not None and current["revision"] in repo.expected
            assert current["files"] == repo.expected[current["revision"]]
            assert current["source"] == identity and current["config"] == config
            checkpoints.append({"name": name, "expected": expected, "actual": current["revision"],
                                "target_met": current["revision"] == expected})

        try:
            store.schedule(0, interval=5)
            drain(0)
            checkpoint("bootstrap", repo.initial)
            version_b = repo.commit({"services/posts/PostRepository.java": "class PostRepository {}\n"})
            if strategy != "poll":
                notify("b", version_b)
            drain(1)
            checkpoint("immediate_change", version_b)
            if strategy != "poll":
                notify("b", version_b)  # same delivery: no new job
                notify("late-a", repo.initial)  # new delivery, obsolete hint
            drain(2)
            checkpoint("late_hint", version_b)
            if strategy != "hints":
                store.schedule(5, interval=5)
            drain(5)
            checkpoint("periodic_convergence", version_b)
            version_c = repo.commit({"services/comments/ReplyService.java": "class ReplyService {}\n"},
                                    ("services/comments/CommentService.java",))
            # A change without any webhook delivery.
            if strategy != "hints":
                store.schedule(10, interval=5)
            drain(10)
            checkpoint("lost_hint_after_period", version_c)
            version_d = repo.commit({"services/posts/PostService.java": "class PostService { void intermediate() {} }\n"})
            version_e = repo.commit({"services/posts/PostService.java": "class PostService { void latest() {} }\n"})
            if strategy != "poll":
                notify("d", version_d)
                notify("e", version_e)
            drain(12)
            checkpoint("coalesced_changes", version_e)
            if strategy != "hints":
                store.schedule(15, interval=5)
            drain(15)
            checkpoint("final_current_state", version_e)
            if strategy != "hints":
                store.schedule(20, interval=5)
            drain(20)
            checkpoint("unchanged_recheck", version_e)
            assert store.state()["requested"] == store.state()["completed"]
            versions = {json.loads(row[0])["revision"] for row in store.db.execute("SELECT body FROM snapshots")}
            assert version_d not in versions  # coalescing cannot preserve unseen intermediate states
            return {"strategy": strategy, "boundary": boundary, "checkpoints": checkpoints,
                    "safety_passed": True, "index_builds": builds, "source_calls": dict(calls),
                    "counts": store.counts(), "work_results": results,
                    "intermediate_revision_not_collected": version_d,
                    "target_misses": sum(not c["target_met"] for c in checkpoints),
                    "elapsed_seconds": time.perf_counter() - started}
        finally:
            store.close()
            receiver.shutdown()
            receiver.server_close()
            thread.join(timeout=5)


def live_smoke():
    """Bounded reads of the owner's public repo; no webhook registration."""
    source = GitHub("DDINGJOO/JJAM-TONG", config=settings(("experiments/",)),
                    token=os.environ.get("JJAMTONG_GITHUB_TOKEN"))
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory) / "public.sqlite", source.source, source.config)
        try:
            records = []
            for step in ("initial_read", "conditional_recheck"):
                store.request()
                result = work(store, source, time.time(), clock=time.time)
                if result["status"] != "published":
                    raise RuntimeError("public GitHub read failed: " + result.get("error", result["status"]))
                records.append({"step": step, "result": result["status"],
                                "index_builds": result["index_builds"]})
            before = store.current()
            assert before["files"]
            success = store.state()["checked_at"]
            source.ref = "jjamtong-intentionally-missing-ref-" + before["revision"]
            store.request()
            failure = work(store, source, time.time(), clock=time.time)
            assert failure["status"] == "failed" and failure["error"] in ("http_404", "http_422"), failure
            assert store.current() == before and store.state()["checked_at"] == success
            records.append({"step": "actual_missing_ref", "result": failure["error"],
                            "previous_success_preserved": True})
            source.ref = "main"
            # Respect the same persisted retry deadline; never bypass rate-limit backoff.
            time.sleep(max(0, store.state()["retry_at"] - time.time()) + 0.01)
            recovered = work(store, source, time.time(), clock=time.time)
            assert recovered["status"] == "published", recovered
            records.append({"step": "actual_source_recovered", "result": recovered["status"]})
            return {"repository": source.repository, "ref": "main", "revision": before["revision"],
                    "api_version": API_VERSION, "selected_file_count": len(before["files"]),
                    "calls": dict(source.calls), "steps": records,
                    "event_delivery": "loopback synthetic only; GitHub webhook not registered"}
        finally:
            store.close()


def markdown(report):
    lines = ["# 원본 재확인·변경 알림 실행 결과", "", "실행일: " + report["recorded_at"], "",
             "[설계·범위](HYBRID-RECONCILIATION.md) · [실험실](../../experiments/reconciliation_lab/README.md) · "
             "[환경·입력 hash·반복 관측값](hybrid-snapshot.json)", "",
             "실제 임시 Git 원본과 loopback HTTP 수신기를 사용했다. 모든 방식은 같은 포함 경로·파일 인덱스·SQLite 계약을 쓴다. "
             "`hints`는 payload 직접 반영이 아니라 원본 재조회를 요청하는 알림 전용 방식이다.", "",
             "## 같은 일정의 반복 비교", "",
             "| 실행 경계 | 갱신 전략 | 반복 | 확인/인덱스 생성¹ | 목표 미달¹ | 경과 중앙값(초)² |", "| --- | --- | --- | --- | --- | --- |"]
    for boundary in BOUNDARIES:
        for strategy in STRATEGIES:
            runs = [r for r in report["runs"] if r["boundary"] == boundary and r["strategy"] == strategy]
            counts = {(r["source_calls"].get("checks", 0), r["index_builds"], r["target_misses"]) for r in runs}
            assert len(counts) == 1
            checks, builds, misses = next(iter(counts))
            median = statistics.median(r["elapsed_seconds"] for r in runs)
            lines.append(f"| {boundary} | {strategy} | {len(runs)} | {checks}/{builds} | {misses} | {median:.4f} |")
    lines += ["", "¹ 한 실행의 수치이며 목표 미달의 분모는 8개 체크포인트다. 같은 변경의 주기 전 지연을 여러 체크포인트에서 볼 수 있어 독립 장애 건수나 성공률로 환산하지 않는다. "
              "² 해당 머신의 fixture 일정 실행 시간으로 원본 Git 명령·HTTP 왕복을 포함한다. "
              "subprocess에는 매 작업의 Python 프로세스 시작 비용이 포함된다. 상시 worker의 처리량·갱신 SLO·우위로 해석하지 않는다.", "",
              "- 즉시 변경은 poll에서 다음 주기까지 지연됐다. hints/hybrid는 수신 뒤 원본을 확인했다.",
              "- 알림이 없는 변경은 poll/hybrid에서 다음 주기에 확인됐고 hints에는 누락됐다.",
              "- 중복·오래된 알림으로 원본이 가리키는 현재 commit을 덮어쓰지 않았다.",
              "- 변경 없는 확인에서는 파일 인덱스 재생성을 건너뛰었다.",
              "- 두 번의 변경을 묶어 처리하면 세 방식 모두 중간 commit의 인덱스를 만들지 못했다. 이벤트 원장이나 모든 커밋 수집의 검증이 아니다.",
              "- 두 실행 경계의 의미상 결과가 일치했다. 단일 머신 SQLite를 공유하므로 다중 머신·broker 장애 격리를 검증하지 않았다.", "",
              "## 실제 공개 GitHub 읽기", ""]
    live = report.get("live_github")
    if live:
        lines += [f"대상: `{live['repository']}` / `main` / `{live['revision']}`. API `{live['api_version']}`. "
                  f"포함 경로 `experiments/`에서 파일 {live['selected_file_count']}개를 확인했다.", "",
                  "| 단계 | 실제 결과 |", "| --- | --- |"]
        for step in live["steps"]:
            lines.append(f"| {step['step']} | {step['result']} |")
        lines += ["", "원본 호출 관측: `" + json.dumps(live["calls"], sort_keys=True) + "`. "
                  "실제 실패는 존재하지 않는 ref의 조회이며 GitHub 서비스 장애를 유발하지 않았다. "
                  "실제 GitHub 발 웹훅·App 설치·권한 회수는 실행하지 않았다."]
    else:
        lines += ["이번 실행에서 실제 GitHub 조회는 선택하지 않았다. HTTP 계약·장애는 loopback 주입 테스트다."]
    lines += ["", "## 판정과 남은 범위", "",
              "별도 unittest는 H01~H14의 정상·실패 계약을 확인한다. 실제 자식 프로세스 종료 두 지점·동시 worker·lease fencing·"
              "연결 회수·설정 변경·backpressure·조건부 HTTP·부분 tree·429 Retry-After를 포함한다. "
              "429와 부분 tree는 loopback 주입이고 연결 회수는 로컬 switch다.", "",
              "앞선 X01~X16·48회 합성 실험의 결과는 별도로 유지한다. 현재 구현은 Git 파일·blob 관계이며 메서드 호출 그래프·"
              "빌드/trace 결합·클러스터·AWS·CMDB·SIEM·다중 tenant/query ACL·전체 BDD 수락은 미실행이다. "
              "처리된 inbox 보존 기간·디스크 상한·lease 갱신·영구 실패 격리·상시 worker 운영도 후속이다.", ""]
    return "\n".join(lines)


def main():
    if not __debug__:
        raise RuntimeError("oracle assertions require normal Python execution, not -O")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("results/reconciliation-lab"))
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--live-github", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 10:
        parser.error("repetitions must be between 1 and 10")
    report = {"recorded_at": datetime.now(timezone.utc).isoformat(),
              "environment": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
                              "os": platform.system(), "machine": platform.machine(),
                              "git": subprocess.run(["git", "--version"], check=True, capture_output=True,
                                                    text=True).stdout.strip()},
              "base_commit": subprocess.run(["git", "rev-parse", "HEAD"], check=True,
                                            capture_output=True, text=True).stdout.strip(),
              "input_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(HERE.glob("*.py"))},
              "runs": []}
    for repeat in range(args.repetitions):
        for boundary in BOUNDARIES:
            for strategy in STRATEGIES:
                report["runs"].append(dict(run_case(strategy, boundary), repetition=repeat + 1))
    for strategy in STRATEGIES:
        runs = [r for r in report["runs"] if r["strategy"] == strategy]
        baseline = runs[0]
        for run in runs[1:]:
            for field in ("checkpoints", "source_calls", "index_builds", "counts", "target_misses"):
                assert run[field] == baseline[field], (strategy, field)
    if args.live_github:
        report["live_github"] = live_smoke()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "hybrid-snapshot.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (args.output / "HYBRID-RESULTS.md").write_text(markdown(report))
    print(json.dumps({"runs": len(report["runs"]), "safety_passed": all(r["safety_passed"] for r in report["runs"]),
                      "checkpoint_target_misses": sum(r["target_misses"] for r in report["runs"]),
                      "live_github": bool(report.get("live_github"))}))


if __name__ == "__main__":
    main()

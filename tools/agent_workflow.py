#!/usr/bin/env python3
"""Local, data-only task completion checks for cooperative agent work.

Hooks never execute recorded validation commands. They only read the manifest,
recompute a bounded source digest, and return a small protocol response.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time

MAX_INPUT = 64 * 1024
MAX_OUTPUT = 400
MAX_SCOPES = 128
MAX_ACCEPTANCE = 128
MAX_FILES = 512
MAX_BYTES = 4 * 1024 * 1024
MAX_FINGERPRINT_SECONDS = 2
STATES = {"planned", "running", "blocked", "deferred", "cancelled", "complete"}
SKIP_PARTS = {".git", ".local", ".omx", "build", "generated", "__pycache__"}
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_DIR = REPO_ROOT / ".local" / "agent-workflow"


def fail(message):
    return {"ok": False, "message": str(message)[:MAX_OUTPUT]}


def nonblank_string(value):
    return isinstance(value, str) and bool(value.strip())


def finite_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def load_json(path, label="manifest"):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        raise ValueError("invalid " + label)
    if not isinstance(value, dict):
        raise ValueError("invalid " + label)
    return value


def normalize_scope(scope):
    if not isinstance(scope, str) or not scope or len(scope) > 1024:
        raise ValueError("invalid scope")
    path = Path(scope)
    if path.is_absolute():
        raise ValueError("invalid scope")
    parts = []
    for part in path.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise ValueError("invalid scope")
            parts.pop()
        else:
            parts.append(part)
    normalized = Path(*parts).as_posix()
    if normalized == "." or any(part in SKIP_PARTS for part in Path(normalized).parts):
        raise ValueError("invalid scope")
    return normalized.rstrip("/")


def normalized_scopes(scopes):
    if not isinstance(scopes, list) or not scopes or len(scopes) > MAX_SCOPES:
        raise ValueError("invalid scopes")
    return sorted({normalize_scope(item) for item in scopes})


def scope_overlap(left, right):
    try:
        left, right = normalized_scopes(left), normalized_scopes(right)
    except ValueError:
        return True
    return any(a == b or a.startswith(b + "/") or b.startswith(a + "/")
               for a in left for b in right)


def source_root(manifest):
    if not isinstance(manifest, dict):
        raise ValueError("invalid manifest")
    run = manifest.get("run", {})
    value = run.get("source_root", str(REPO_ROOT)) if isinstance(run, dict) else str(REPO_ROOT)
    if not isinstance(value, str) or not value:
        raise ValueError("invalid source root")
    root = Path(value).resolve()
    if not root.is_dir():
        raise ValueError("invalid source root")
    return root


def fingerprint_scopes(root, scopes):
    """Return a deterministic digest without following symlinks or caches."""
    root = Path(root).resolve()
    digest, files, size = hashlib.sha256(), 0, 0
    deadline = time.monotonic() + MAX_FINGERPRINT_SECONDS

    def check_deadline():
        if time.monotonic() > deadline:
            raise ValueError("source fingerprint limit exceeded")

    def check_path(path):
        nonlocal files, size
        check_deadline()
        if path.is_symlink():
            raise ValueError("owned scope contains symlink")
        if not path.is_file():
            return
        try:
            relative = path.relative_to(root).as_posix().encode("utf-8")
            data_size = path.stat().st_size
        except (OSError, ValueError):
            raise ValueError("owned scope unavailable")
        files, size = files + 1, size + data_size
        if files > MAX_FILES or size > MAX_BYTES:
            raise ValueError("source fingerprint limit exceeded")
        digest.update(len(relative).to_bytes(4, "big")); digest.update(relative)
        try:
            with path.open("rb") as source:
                while chunk := source.read(65536):
                    check_deadline()
                    digest.update(chunk)
        except OSError:
            raise ValueError("owned scope unavailable")

    for scope in normalized_scopes(scopes):
        candidate = root / scope
        ancestor = root
        for part in Path(scope).parts:
            ancestor /= part
            check_deadline()
            if ancestor.is_symlink():
                raise ValueError("owned scope escapes source root")
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            raise ValueError("owned scope unavailable")
        if not resolved.is_relative_to(root):
            raise ValueError("owned scope escapes source root")
        if not candidate.is_dir():
            check_path(candidate)
            continue
        for current, dirs, names in os.walk(candidate, followlinks=False):
            check_deadline()
            current_path = Path(current)
            kept_dirs = []
            for name in sorted(dirs):
                check_deadline()
                path = current_path / name
                if name in SKIP_PARTS:
                    continue
                if path.is_symlink():
                    raise ValueError("owned scope contains symlink")
                kept_dirs.append(name)
            dirs[:] = kept_dirs
            for name in sorted(names):
                check_path(current_path / name)
    return "sha256:" + digest.hexdigest()


def task_fingerprint(manifest, task):
    if not isinstance(task, dict):
        raise ValueError("invalid task")
    return fingerprint_scopes(source_root(manifest), task.get("scopes", []))


def evidence_current(task, run, fingerprint):
    # These are operator-recorded facts, not cryptographic command attestation.
    evidence = task.get("validation", [])
    if not isinstance(evidence, list) or not evidence:
        return False
    for item in evidence:
        if not isinstance(item, dict) or item.get("status") != "pass":
            return False
        if not nonblank_string(item.get("command")):
            return False
        if (not isinstance(item.get("exit_code"), int) or isinstance(item["exit_code"], bool)
                or item["exit_code"] != 0
                or not nonblank_string(item.get("version"))
                or item["version"] != run.get("version")):
            return False
        if (not nonblank_string(item.get("revision"))
                or not nonblank_string(item.get("fingerprint"))
                or item["revision"] != run.get("revision")
                or item["fingerprint"] != fingerprint):
            return False
        if not finite_number(item.get("timestamp")) or item["timestamp"] <= 0:
            return False
        if not nonblank_string(item.get("reference")):
            return False
    return True


def qa_current(task, run, fingerprint):
    if not task.get("milestone"):
        return True
    assessments, found = task.get("assessments", []), set()
    if not isinstance(assessments, list):
        return False
    for item in assessments:
        if not isinstance(item, dict) or item.get("kind") not in {"human", "agent"}:
            return False
        if not all(nonblank_string(item.get(field)) for field in ("version", "revision", "fingerprint")):
            return False
        bound = (item["version"] == run.get("version")
                 and item["revision"] == run.get("revision")
                 and item["fingerprint"] == fingerprint)
        if item.get("status") == "pass":
            qualified = nonblank_string(item.get("reviewer")) and item["reviewer"] != task.get("owner")
        elif item.get("status") == "na":
            qualified = (nonblank_string(item.get("reason"))
                         and nonblank_string(item.get("coordinator"))
                         and item["coordinator"] != task.get("owner"))
        else:
            qualified = False
        if bound and qualified:
            found.add(item["kind"])
    return {"human", "agent"}.issubset(found)


def evaluate(manifest, fingerprints=None):
    if not isinstance(manifest, dict):
        return fail("invalid manifest")
    run, tasks = manifest.get("run"), manifest.get("tasks")
    if not isinstance(run, dict) or not all(nonblank_string(run.get(key)) for key in ("id", "version", "revision", "source_scope")):
        return fail("run requires id, version, revision, and source_scope")
    if not isinstance(tasks, list) or len(tasks) > MAX_SCOPES:
        return fail("tasks must be a bounded list")
    ids, errors, pending = {}, [], []
    for task in tasks:
        if not isinstance(task, dict) or not all(nonblank_string(task.get(key)) for key in ("id", "ticket", "lane", "owner", "role")):
            errors.append("task requires id, ticket, lane, owner, and role"); continue
        if task["id"] in ids: errors.append("duplicate task id " + task["id"])
        ids[task["id"]] = task
        if task.get("state") not in STATES: errors.append("invalid state for " + task["id"])
        if not isinstance(task.get("result"), dict) or task["result"].get("state") not in {"complete", "partial", "unknown"}:
            errors.append("task requires result state " + task["id"])
        try: normalized_scopes(task.get("scopes", []))
        except ValueError: errors.append("task requires valid scopes " + task["id"])
        if task.get("state") in {"blocked", "deferred"} and (not isinstance(task.get("reason"), str) or not task["reason"].strip()):
            errors.append("blocked/deferred task requires reason " + task["id"])
    graph = {}
    for task_id, task in ids.items():
        dependencies = task.get("dependencies", [])
        if (not isinstance(dependencies, list) or len(dependencies) > MAX_SCOPES
                or any(not isinstance(dep, str) or dep not in ids for dep in dependencies)):
            errors.append("unknown dependency " + task_id); dependencies = []
        graph[task_id] = dependencies
        if task.get("state") in {"running", "complete"} and any(ids[dep].get("state") != "complete" for dep in dependencies):
            errors.append("task has incomplete dependency " + task_id)
        fingerprint = (fingerprints or {}).get(task_id, run.get("source_fingerprint"))
        result = task.get("result")
        acceptance = task.get("acceptance")
        if task.get("state") == "complete" and (not isinstance(result, dict) or result.get("state") != "complete"
                or not isinstance(acceptance, list) or not acceptance or len(acceptance) > MAX_ACCEPTANCE
                or not all(nonblank_string(item) for item in acceptance)
                or not nonblank_string(fingerprint) or not evidence_current(task, run, fingerprint)
                or not qa_current(task, run, fingerprint)):
            errors.append("completion evidence incomplete " + task_id)
        if task.get("state") not in {"complete", "cancelled"}:
            pending.append({"id": task_id, "state": task.get("state"), "reason": task.get("reason", "pending completion")})
    visiting, visited = set(), set()
    def visit(task_id):
        if task_id in visiting:
            return True
        if task_id in visited:
            return False
        visiting.add(task_id)
        cycle = any(visit(dependency) for dependency in graph[task_id])
        visiting.remove(task_id)
        visited.add(task_id)
        return cycle
    if any(visit(task_id) for task_id in graph):
        errors.append("task dependency cycle")
    active = [task for task in ids.values() if task.get("state") == "running"]
    for index, task in enumerate(active):
        for other in active[index + 1:]:
            if task.get("owner") == other.get("owner"): errors.append("owner has multiple running leaves " + task["owner"])
            if scope_overlap(task.get("scopes", []), other.get("scopes", [])):
                errors.append("running write scopes overlap " + task["id"] + "/" + other["id"])
    return {"ok": not errors, "message": "; ".join(errors)[:MAX_OUTPUT] if errors else "valid", "run": run.get("id"), "pending": pending, "task_count": len(tasks)}


def state_path(root): return Path(root) / "state.json"


def read_state(root):
    path = state_path(root)
    try:
        if not path.exists(): return {"sessions": {}}
        value = load_json(path, "workflow state")
        if not isinstance(value.get("sessions", {}), dict): raise ValueError("invalid workflow state")
        return value
    except (OSError, ValueError):
        return {"sessions": {}, "state_error": "workflow state invalid"}


def write_state(root, value):
    root = Path(root); root.mkdir(parents=True, exist_ok=True); lock = root / "state.lock"
    for _ in range(100):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY); os.close(fd); break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 30: lock.unlink(); continue
            except FileNotFoundError: continue
            time.sleep(.01)
    else: raise ValueError("state is busy")
    try:
        current = read_state(root)
        if current.get("state_error"): raise ValueError(current["state_error"])
        if isinstance(current.get("sessions"), dict) and isinstance(value.get("sessions"), dict):
            value["sessions"] = dict(current["sessions"], **value["sessions"])
        fd, name = tempfile.mkstemp(prefix=".state-", dir=root)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(value, output, separators=(",", ":")); output.flush(); os.fsync(output.fileno())
        os.replace(name, state_path(root))
    finally:
        try: lock.unlink()
        except FileNotFoundError: pass


def check(manifest_path, root):
    try:
        manifest = load_json(manifest_path)
    except ValueError:
        return fail("invalid manifest")
    state = read_state(root)
    if state.get("state_error"): return fail(state["state_error"])
    fingerprints = {}
    try:
        for task in manifest.get("tasks", []):
            if isinstance(task, dict) and isinstance(task.get("id"), str): fingerprints[task["id"]] = task_fingerprint(manifest, task)
    except (ValueError, OSError, TypeError) as error:
        return fail(str(error))
    result = evaluate(manifest, fingerprints)
    snapshot = {"manifest": str(Path(manifest_path).resolve()), "checked_at": int(time.time()), "result": result,
                "tasks": manifest.get("tasks", []), "run": manifest.get("run", {}), "fingerprints": fingerprints, "sessions": state.get("sessions", {})}
    write_state(root, snapshot)
    return result


def session_key(tool, session_id):
    return tool + ":" + session_id


def bind(args):
    if args.tool not in {"codex", "claude"} or not nonblank_string(args.session_id):
        return fail("invalid tool or session id")
    manifest = load_json(args.manifest)
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or not any(isinstance(task, dict) and task.get("id") == args.task for task in tasks):
        return fail("bound task unavailable")
    state = read_state(args.state_dir)
    if state.get("state_error"): return fail(state["state_error"])
    state.setdefault("sessions", {})[session_key(args.tool, args.session_id)] = {"task_id": args.task, "manifest": str(Path(args.manifest).resolve())}
    write_state(args.state_dir, state)
    return {"ok": True, "message": "task session bound", "task": args.task}


def hook(args):
    raw = sys.stdin.buffer.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT: return fail("hook input too large")
    try: event = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError): return fail("invalid hook input")
    if not isinstance(event, dict): return fail("invalid hook input")
    args.event_name = event.get("hook_event_name") if isinstance(event.get("hook_event_name"), str) else ""
    event_name, session_id = args.event_name, event.get("session_id")
    if event_name in {"Stop", "SubagentStop"} and event.get("stop_hook_active") is True:
        return {"ok": True, "message": "workflow stop check already active"}
    # Subagents do not inherit a parent session's completion gate.  A future
    # explicit child binding can add a separate policy without changing this
    # safe default for client/internal child events.
    if event_name == "SubagentStop":
        return {"ok": True, "message": "workflow advisory: subagent stop"}
    state = read_state(args.state_dir)
    if state.get("state_error"):
        if event_name == "Stop":
            return {"ok": True, "message": "workflow advisory: state unavailable"}
        return {"ok": True, "message": "workflow advisory: workflow state invalid"}
    binding = (state.get("sessions", {}).get(session_key(args.tool, session_id))
               if nonblank_string(session_id) else None)
    if event_name in {"SessionStart", "UserPromptSubmit"}:
        return {"ok": True, "message": "workflow skill: bound validation+QA contract" if binding else "workflow skill: advisory bind task for completion contract"}
    if event_name != "Stop": return {"ok": True, "message": "workflow advisory: unsupported event"}
    if not isinstance(binding, dict): return {"ok": True, "message": "workflow advisory: no bound task"}
    manifest = binding.get("manifest")
    if not isinstance(manifest, str): return fail("bound task manifest unavailable")
    result = check(manifest, args.state_dir)
    if not result.get("ok"):
        if result.get("message") == "invalid manifest":
            return fail("bound task manifest unavailable")
        return fail("bound task incomplete")
    try: task = next(item for item in load_json(manifest).get("tasks", []) if isinstance(item, dict) and item.get("id") == binding.get("task_id"))
    except (ValueError, StopIteration): return fail("bound task unavailable")
    if task.get("state") in {"blocked", "deferred", "cancelled"}:
        return {"ok": True, "message": "task " + task["state"] + ": " + str(task.get("reason", "unresolved"))[:200]}
    if task.get("state") != "complete": return fail("bound task incomplete")
    return {"ok": True, "message": "bound task complete"}


def hook_wire(event_name, result):
    message = str(result.get("message", "workflow check"))[:MAX_OUTPUT]
    if event_name in {"Stop", "SubagentStop"}:
        return {} if result.get("ok") else {"decision": "block", "reason": message}
    return {"hookSpecificOutput": {"hookEventName": event_name or "UserPromptSubmit", "additionalContext": message}}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    subs = parser.add_subparsers(dest="command", required=True)
    check_parser = subs.add_parser("check"); check_parser.add_argument("--manifest", required=True)
    fingerprint_parser = subs.add_parser("fingerprint"); fingerprint_parser.add_argument("--manifest", required=True); fingerprint_parser.add_argument("--task", required=True)
    bind_parser = subs.add_parser("bind"); bind_parser.add_argument("--manifest", required=True); bind_parser.add_argument("--task", required=True); bind_parser.add_argument("--session-id", required=True); bind_parser.add_argument("--tool", required=True, choices=("codex", "claude"))
    subs.add_parser("status")
    hook_parser = subs.add_parser("hook"); hook_parser.add_argument("--tool", required=True, choices=("codex", "claude"))
    args = parser.parse_args(argv)
    try:
        if args.command == "check": result = check(args.manifest, args.state_dir)
        elif args.command == "fingerprint":
            manifest = load_json(args.manifest); task = next((item for item in manifest.get("tasks", []) if isinstance(item, dict) and item.get("id") == args.task), None)
            result = {"ok": True, "task": args.task, "fingerprint": task_fingerprint(manifest, task)} if task else fail("task unavailable")
        elif args.command == "bind": result = bind(args)
        elif args.command == "status":
            value = read_state(args.state_dir); result = fail(value["state_error"]) if value.get("state_error") else value.get("result", fail("no workflow state")); result["pending"] = result.get("pending", [])
        else:
            result = hook(args); print(json.dumps(hook_wire(getattr(args, "event_name", ""), result), separators=(",", ":"))); return 0
    except (ValueError, OSError) as error: result = fail(str(error))
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result.get("ok") else 1


if __name__ == "__main__": raise SystemExit(main())

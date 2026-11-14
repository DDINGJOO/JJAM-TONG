"""Bounded, atomic launcher for the source-only service index."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEPS = REPO / "tools/java-call-analysis/target/dependency"
OUT = REPO / ".local/service-page/compiler"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compile_helper(java_home: Path) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    target, source = OUT / "SourceIndex.class", HERE / "SourceIndex.java"
    if not target.exists() or target.stat().st_mtime < source.stat().st_mtime:
        subprocess.run(
            [str(java_home / "bin/javac"), "-cp", str(DEPS / "*"), "-d", str(OUT), str(source)],
            check=True, timeout=60,
        )
    return OUT


def wait_with_rss(process: subprocess.Popen, deadline: float) -> tuple[int, int]:
    """Reap exactly once with wait4 so the JVM high-water mark belongs to this run."""
    while True:
        pid, status, usage = os.wait4(process.pid, os.WNOHANG)
        if pid:
            process.returncode = os.waitstatus_to_exitcode(status)
            rss = usage.ru_maxrss
            # Darwin returns bytes; Linux and other POSIX hosts conventionally return KiB.
            return process.returncode, rss if sys.platform == "darwin" else rss * 1024
        if time.monotonic() >= deadline:
            process.kill()
            _, status, usage = os.wait4(process.pid, 0)
            process.returncode = os.waitstatus_to_exitcode(status)
            raise TimeoutError
        time.sleep(0.02)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--java-home", required=True, type=Path)
    parser.add_argument("--deadline", type=int, default=120)
    parser.add_argument("--label", default="service")
    args = parser.parse_args()
    if args.deadline <= 0:
        parser.error("--deadline must be positive")
    source = args.source.resolve()
    if not source.is_dir() or not (args.java_home / "bin/java").is_file() or not DEPS.is_dir():
        parser.error("source, java-home, or cached JavaParser dependencies unavailable")
    try:
        compiler = compile_helper(args.java_home)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f"service source compiler failed: {error}", file=sys.stderr)
        return getattr(error, "returncode", 1) or 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    before = time.monotonic()
    fd, name = tempfile.mkstemp(prefix=".jjamtong-service-index-", suffix=".json", dir=args.output.parent)
    os.close(fd)
    temporary = Path(name)
    temporary.unlink()  # SourceIndex requires a non-existent publication target.
    command = [
        str(args.java_home / "bin/java"), "-Xmx2g",
        "-Djava.io.tmpdir=" + str(args.output.parent),
        "-cp", f"{compiler}:{DEPS}/*", "SourceIndex",
        "--source", str(source), "--output", str(temporary), "--label", args.label,
    ]
    try:
        process = subprocess.Popen(command)
        returncode, max_rss = wait_with_rss(process, before + args.deadline)
        if returncode:
            return returncode
        if not temporary.is_file():
            print("service source collection produced no result; no output published", file=sys.stderr)
            return 1
        payload = json.loads(temporary.read_text(encoding="utf-8"))
        elapsed = time.monotonic() - before
        payload["metrics"]["maxRssBytes"] = max_rss
        payload["metrics"]["endToEndSeconds"] = elapsed
        provenance = payload.setdefault("provenance", {})
        provenance["analyzerImplementationSha256"] = sha256(HERE / "SourceIndex.java")
        provenance["launcherImplementationSha256"] = sha256(Path(__file__).resolve())
        provenance["launcherParsePolicy"] = (
            "JVM child reaped with wait4; Darwin RSS bytes, other POSIX RSS KiB normalized"
        )
        replacement = temporary.with_suffix(".ready")
        replacement.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        os.replace(replacement, args.output)
        print(f"service source collection complete: {elapsed:.3f}s, JVM maxRSS {max_rss} bytes")
        return 0
    except TimeoutError:
        print("service source collection timed out; no output published", file=sys.stderr)
        return 124
    finally:
        temporary.unlink(missing_ok=True)
        temporary.with_suffix(".ready").unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())

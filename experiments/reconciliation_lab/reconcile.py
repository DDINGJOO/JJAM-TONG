"""Durable, source-scoped work hints and fenced snapshot publication."""
import hashlib
import json
import sqlite3
import uuid
from .adapters import GitHub, ReadFailure, canonical, fingerprint


class IntakeRejected(Exception):
    def __init__(self, code, status):
        super().__init__(code)
        self.status = status


class Store:
    def __init__(self, path, source, config, capacity=100):
        self.source, self.config, self.capacity = source, config, capacity
        self.db = sqlite3.connect(str(path), timeout=5, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS state (
              id INTEGER PRIMARY KEY CHECK(id=1), source TEXT NOT NULL, config_key TEXT NOT NULL,
              enabled INTEGER NOT NULL DEFAULT 1, generation INTEGER NOT NULL DEFAULT 0,
              requested INTEGER NOT NULL DEFAULT 0, completed INTEGER NOT NULL DEFAULT 0,
              token TEXT, lease_until REAL NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0,
              next_due REAL NOT NULL DEFAULT 0, checked_at REAL, error TEXT,
              current_id TEXT, cache TEXT
            );
            CREATE TABLE IF NOT EXISTS receipts (
              delivery TEXT PRIMARY KEY, digest TEXT NOT NULL,
              request_n INTEGER NOT NULL, done INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS snapshots (id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS observations (
              sequence INTEGER PRIMARY KEY, snapshot_id TEXT NOT NULL, observed_at REAL NOT NULL
            );
        """)
        self.db.execute("INSERT OR IGNORE INTO state(id,source,config_key) VALUES(1,?,?)", (source, fingerprint(config)))
        if self.state()["source"] != source:
            self.close()
            raise ValueError("database bound to a different source")
        if self.state()["config_key"] != fingerprint(config):
            self.close()
            raise ValueError("analysis configuration changed; reconfigure explicitly first")

    def close(self):
        self.db.close()

    def state(self):
        return dict(self.db.execute("SELECT * FROM state WHERE id=1").fetchone())

    def current(self):
        row = self.db.execute("SELECT body FROM snapshots WHERE id=(SELECT current_id FROM state)").fetchone()
        return json.loads(row[0]) if row else None

    def counts(self):
        return {name: self.db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
                for name in ("receipts", "snapshots", "observations")}

    def _begin(self):
        self.db.execute("BEGIN IMMEDIATE")

    def _request(self, delivery=None, digest=None):
        state = self.state()
        if not state["enabled"]:
            raise IntakeRejected("connection_disabled", 403)
        if delivery is not None:
            old = self.db.execute("SELECT digest FROM receipts WHERE delivery=?", (delivery,)).fetchone()
            if old:
                if old[0] != digest:
                    raise IntakeRejected("delivery_payload_conflict", 409)
                return "duplicate"
            pending = self.db.execute("SELECT COUNT(*) FROM receipts WHERE done=0").fetchone()[0]
            if pending >= self.capacity:
                raise IntakeRejected("inbox_full", 503)
        number = state["requested"] + 1
        self.db.execute("UPDATE state SET requested=? WHERE id=1", (number,))
        if delivery is not None:
            self.db.execute("INSERT INTO receipts VALUES(?,?,?,0)", (delivery, digest, number))
        return "accepted"

    def request(self, delivery=None, digest=None):
        self._begin()
        try:
            result = self._request(delivery, digest)
            self.db.commit()
            return result
        except BaseException:
            self.db.rollback()
            raise

    def schedule(self, now, interval=60, jitter=0):
        if interval <= 0 or jitter < 0:
            raise ValueError("positive interval and nonnegative jitter required")
        self._begin()
        try:
            state = self.state()
            due = bool(state["enabled"] and now >= state["next_due"])
            if due:
                self._request()
                self.db.execute("UPDATE state SET next_due=? WHERE id=1", (now + interval + jitter,))
            self.db.commit()
            return due
        except BaseException:
            self.db.rollback()
            raise

    def claim(self, now, lease=30):
        self._begin()
        try:
            state = self.state()
            if state["config_key"] != fingerprint(self.config):
                raise ValueError("worker analysis configuration is obsolete")
            if (not state["enabled"] or state["requested"] <= state["completed"]
                    or now < state["retry_at"] or (state["token"] and now < state["lease_until"])):
                self.db.commit()
                return None
            state["token"] = uuid.uuid4().hex
            self.db.execute("UPDATE state SET token=?,lease_until=? WHERE id=1", (state["token"], now + lease))
            self.db.commit()
            return state
        except BaseException:
            self.db.rollback()
            raise

    def _owns(self, claim, now):
        state = self.state()
        return (state["enabled"] and state["generation"] == claim["generation"]
                and state["config_key"] == fingerprint(self.config)
                and state["token"] == claim["token"] and now < state["lease_until"])

    def publish(self, claim, snapshot, etag, now, fault=None):
        self._begin()
        try:
            if not self._owns(claim, now):
                self.db.rollback()
                return False
            if snapshot["source"] != self.source or snapshot["config"] != self.config:
                raise ValueError("source or analysis scope mismatch")
            key = hashlib.sha256(canonical([self.source, snapshot["revision"], fingerprint(self.config)]).encode()).hexdigest()
            body = canonical(snapshot)
            old = self.db.execute("SELECT body FROM snapshots WHERE id=?", (key,)).fetchone()
            if old and old[0] != body:
                raise ValueError("immutable snapshot conflict")
            self.db.execute("INSERT OR IGNORE INTO snapshots VALUES(?,?)", (key, body))
            if self.state()["current_id"] != key:
                self.db.execute("INSERT INTO observations(snapshot_id,observed_at) VALUES(?,?)", (key, now))
            if fault:
                fault()
            self.db.execute("""UPDATE state SET current_id=?,cache=?,checked_at=?,completed=?,
                            error=NULL,token=NULL,lease_until=0,retry_at=0 WHERE id=1""",
                            (key, canonical({"etag": etag, "snapshot": snapshot}), now, claim["requested"]))
            self.db.execute("UPDATE receipts SET done=1 WHERE request_n<=?", (claim["requested"],))
            self.db.commit()
            return True
        except BaseException:
            self.db.rollback()
            raise

    def fail(self, claim, error, now):
        self._begin()
        try:
            if self._owns(claim, now):
                self.db.execute("UPDATE state SET error=?,retry_at=?,token=NULL,lease_until=0 WHERE id=1",
                                (str(error), now + error.retry_after))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def revoke(self):
        self.db.execute("UPDATE state SET enabled=0,generation=generation+1,token=NULL WHERE id=1")

    def reconfigure(self, config):
        self.db.execute("""UPDATE state SET config_key=?,generation=generation+1,token=NULL,
                        retry_at=0,requested=requested+1 WHERE id=1""", (fingerprint(config),))
        self.config = config


def work(store, source, now, fault=None, clock=None):
    """clock allows tests to model I/O time; production-like runs use wall time."""
    if source.source != store.source or source.config != store.config:
        raise ValueError("worker source or analysis configuration mismatch")
    claim = store.claim(now)
    if claim is None:
        return {"status": "idle", "calls": {}}
    cache = json.loads(claim["cache"]) if claim["cache"] else {}
    previous = cache.get("snapshot")
    if previous and previous["config"] != store.config:
        previous, cache = None, {}
    try:
        if isinstance(source, GitHub):
            snapshot, etag = source.read(previous, cache.get("etag"))
        else:
            snapshot, etag = source.read(previous)
        old_files = previous["files"] if previous else {}
        new_files = snapshot["files"]
        delta = {"added": sorted(set(new_files) - set(old_files)),
                 "removed": sorted(set(old_files) - set(new_files)),
                 "changed": sorted(p for p in set(old_files) & set(new_files) if old_files[p] != new_files[p])}
        finished = clock() if clock else now
        published = store.publish(claim, snapshot, etag, finished, fault)
        return {"status": "published" if published else "fenced",
                "index_builds": int(previous is None or previous != snapshot),
                "path_delta": delta, "calls": dict(source.calls)}
    except ReadFailure as error:
        store.fail(claim, error, clock() if clock else now)
        return {"status": "failed", "error": str(error), "retry_after": error.retry_after,
                "calls": dict(source.calls)}

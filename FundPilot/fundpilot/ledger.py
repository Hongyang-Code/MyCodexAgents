"""Private SQLite append-only event store (not a tamper-proof external audit log).

Store databases outside the checkout. Append is atomic across processes, with
optimistic stream-version checks. Backups use SQLite's consistent backup API.
"""
import json
import os
import stat
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class ConflictError(ValueError):
    """A reused event ID or stale expected stream version conflicts."""


def timestamp(value=None):
    """Return an aware ISO timestamp; reject naive or malformed input."""
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone required")
    return parsed.astimezone(timezone.utc).isoformat()


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _private_file(path, *, exclusive=False):
    """Create private file/parents without following any path-component symlink.

    Existing ancestor permissions are not changed. Host administrators remain
    trusted; this is filesystem hygiene, not isolation from a malicious host.
    """
    target = Path(os.path.abspath(os.fspath(path)))
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in target.parts[1:-1]:
            try:
                os.mkdir(component, mode=0o700, dir_fd=directory)
            except FileExistsError:
                pass
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
        if exclusive:
            flags |= os.O_EXCL
        fd = os.open(target.name, flags, 0o600, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("private state must be a regular, unlinked file")
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        for suffix in ("-wal", "-shm", "-journal"):
            try:
                info = os.stat(target.name + suffix, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("unsafe SQLite sidecar")
            fd = os.open(target.name + suffix, os.O_RDWR | os.O_NOFOLLOW, dir_fd=directory)
            try:
                os.fchmod(fd, 0o600)
            finally:
                os.close(fd)
    finally:
        os.close(directory)
    return str(target)


class Ledger:
    """Ledger(path). append returns {version,event_id,kind,payload,occurred_at}.

    Identical retries return the original event even with a stale expected_version.
    Explicit timestamps participate in duplicate checking; generated timestamps do
    not. expected_version is optional for independent events, required by callers
    implementing read-modify-write projections such as PortfolioManager.
    """
    def __init__(self, path):
        self.path = str(path) if str(path) == ":memory:" else _private_file(path)
        self.connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS events (
              version INTEGER PRIMARY KEY AUTOINCREMENT,
              event_id TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
              payload TEXT NOT NULL, occurred_at TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
              BEGIN SELECT RAISE(ABORT, 'append-only'); END;
            CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
              BEGIN SELECT RAISE(ABORT, 'append-only'); END;
        ''')

    @property
    def version(self):
        return self.connection.execute("SELECT COALESCE(MAX(version),0) FROM events").fetchone()[0]

    @staticmethod
    def _decode(row):
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        return result

    def get(self, event_id):
        row = self.connection.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
        return self._decode(row) if row else None

    def append(self, event_id, kind, payload, *, expected_version=None, occurred_at=None):
        if not isinstance(event_id, str) or not event_id.strip() or not isinstance(kind, str) or not kind.strip():
            raise ValueError("nonempty event ID and kind required")
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        if expected_version is not None and (type(expected_version) is not int or expected_version < 0):
            raise ValueError("invalid expected_version")
        encoded = canonical(payload)
        at = timestamp(occurred_at)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            old = self.get(event_id)
            if old:
                if old["kind"] != kind or canonical(old["payload"]) != encoded or (occurred_at is not None and old["occurred_at"] != at):
                    raise ConflictError("event ID reused with different content")
                self.connection.execute("COMMIT")
                return old
            if expected_version is not None and self.version != expected_version:
                raise ConflictError("stream version changed; reload and retry")
            self.connection.execute("INSERT INTO events(event_id,kind,payload,occurred_at) VALUES (?,?,?,?)", (event_id, kind, encoded, at))
            result = self.get(event_id)
            self.connection.execute("COMMIT")
            return result
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def events(self, kind=None):
        rows = self.connection.execute("SELECT * FROM events ORDER BY version" if kind is None else "SELECT * FROM events WHERE kind=? ORDER BY version", () if kind is None else (kind,))
        return [self._decode(row) for row in rows]

    def integrity_check(self):
        return self.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    def backup(self, path):
        """Create a consistent backup at a NEW path; reopen it with Ledger to restore.

        Never overwrites a backup or live database. Files contain private data.
        """
        target = _private_file(path, exclusive=True)
        destination = sqlite3.connect(target)
        try:
            self.connection.backup(destination)
        finally:
            destination.close()

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

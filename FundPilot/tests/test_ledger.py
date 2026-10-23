"""Synthetic-only persistence and conflict tests."""
import os
import stat
import sqlite3
import tempfile
import unittest
from pathlib import Path
from fundpilot.ledger import Ledger, ConflictError


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "private.sqlite"
        self.ledger = Ledger(self.path)

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def test_duplicate_and_conflict(self):
        first = self.ledger.append("a", "test", {"value": "1"}, expected_version=0)
        self.assertEqual(first, self.ledger.append("a", "test", {"value": "1"}, expected_version=0))
        with self.assertRaises(ConflictError):
            self.ledger.append("a", "test", {"value": "2"})
        self.assertEqual(self.ledger.version, 1)

    def test_cross_connection_version_and_restart(self):
        with Ledger(self.path) as second:
            second.append("a", "test", {})
            with self.assertRaises(ConflictError):
                self.ledger.append("b", "test", {}, expected_version=0)
        with Ledger(self.path) as restarted:
            self.assertEqual(restarted.version, 1)
            self.assertTrue(restarted.integrity_check())

    def test_immutable_and_restore(self):
        self.ledger.append("a", "test", {"synthetic": True})
        for command in ("DELETE FROM events", "UPDATE events SET kind='evil'"):
            with self.assertRaises(sqlite3.IntegrityError):
                self.ledger.connection.execute(command)
        backup = Path(self.tmp.name) / "backup.sqlite"
        self.ledger.backup(backup)
        self.ledger.append("b", "test", {})
        with Ledger(backup) as restored:
            self.assertEqual(restored.version, 1)
            self.assertEqual(restored.events()[0]["payload"], {"synthetic": True})
        with self.assertRaises(FileExistsError):
            self.ledger.backup(backup)

    def test_reject_invalid_input_without_write(self):
        for args in [("", "test", {}), ("a", "test", {"bad": float("nan")})]:
            with self.assertRaises(ValueError):
                self.ledger.append(*args)
        with self.assertRaises(ValueError):
            self.ledger.append("a", "test", {}, occurred_at="2026-01-01T00:00:00")
        self.assertEqual(self.ledger.version, 0)

    def test_private_permissions_and_created_parent(self):
        path = Path(self.tmp.name) / "nested" / "private" / "ledger.sqlite"
        with Ledger(path) as private:
            private.append("one", "test", {})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.parent.parent.stat().st_mode), 0o700)
            for suffix in ("-wal", "-shm"):
                self.assertEqual(stat.S_IMODE(Path(str(path) + suffix).stat().st_mode), 0o600)
            backup = path.parent / "backup.sqlite"
            private.backup(backup)
            self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
        os.chmod(path, 0o644)
        with Ledger(path):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_reject_symlinks_for_database_parent_sidecar_and_backup(self):
        link = Path(self.tmp.name) / "link.sqlite"
        link.symlink_to(self.path)
        with self.assertRaises(OSError):
            Ledger(link)
        parent_link = Path(self.tmp.name) / "parentlink"
        parent_link.symlink_to(self.tmp.name, target_is_directory=True)
        with self.assertRaises(OSError):
            Ledger(parent_link / "new.sqlite")
        with self.assertRaises(OSError):
            self.ledger.backup(link)
        victim = Path(self.tmp.name) / "victim"
        victim.write_text("do not alter")
        unsafe = Path(self.tmp.name) / "unsafe.sqlite"
        Path(str(unsafe) + "-wal").symlink_to(victim)
        with self.assertRaises(ValueError):
            Ledger(unsafe)
        self.assertEqual(victim.read_text(), "do not alter")

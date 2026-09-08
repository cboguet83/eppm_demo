"""Seeding must preserve the complete previous database before any writes."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.seed_database import seed_database
from src.database.seeder import seed_default_data_if_empty


class SeedBackupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "data" / "test.db"
        self.path.parent.mkdir()

    def backups(self):
        return list((self.path.parent / "backups").glob("*.db"))

    def test_force_and_append_seed_back_up_existing_data_once(self):
        seed_database(2, 0, 0, str(self.path))
        seed_database(3, 0, 0, str(self.path), clean_first=False)
        self.assertEqual(len(self.backups()), 1)
        with sqlite3.connect(self.backups()[0]) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM project").fetchone()[0], 2)
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        seed_default_data_if_empty(str(self.path), force=True)
        self.assertEqual(len(self.backups()), 2)
        seed_default_data_if_empty(str(self.path))
        self.assertEqual(len(self.backups()), 2)  # No-op startup is not a new seed.

    def test_backup_failure_aborts_before_seed_changes(self):
        seed_database(2, 0, 0, str(self.path))
        with patch("src.database.backup.backup_database", side_effect=OSError("Disk full")):
            with self.assertRaises(OSError):
                seed_database(3, 0, 0, str(self.path))
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM project").fetchone()[0], 2)

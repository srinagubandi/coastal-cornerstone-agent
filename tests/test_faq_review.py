"""Tests for faq_review module."""
import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from store import Store
from faq_review import FAQReview, Conflict, read_public_snapshot, ALLOWED_EMAIL, ALLOWED_PHONE

class TestFAQReview(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = Store(self.temp_dir.name)
        # Create a base_snapshot of 50 fake questions
        self.base_snapshot = [
            {
                "id": f"base-{i}",
                "question": f"What is the process for building a {i}?",
                "answer": f"The process involves step {i}.",
                "source_urls": ["https://cccbuild.com/faq"],
                "tags": ["construction"]
            }
            for i in range(50)
        ]
        self.faq_review = FAQReview(self.store, self.base_snapshot)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _generate_seed(self, count, prefix="seed"):
        """Generate a list of fake question dicts."""
        return [
            {
                "question": f"{prefix} question {i}?",
                "answer": f"{prefix} answer {i}.",
                "source_urls": ["https://cccbuild.com/faq"],
                "tags": ["test"],
                "source_kind": "draft_file",
                "source_id": f"{prefix}-{i}"
            }
            for i in range(count)
        ]

    def test_import_100_questions(self):
        seed = self._generate_seed(100)
        count = self.faq_review.import_questions(seed)
        self.assertEqual(count, 100)
        # Reimport same seed should import 0
        count2 = self.faq_review.import_questions(seed)
        self.assertEqual(count2, 0)
        # All drafts should be in state 'new'
        drafts = self.faq_review.list_drafts()
        self.assertEqual(len(drafts), 100)
        for d in drafts:
            self.assertEqual(d["state"], "new")
        # Baseline unchanged
        snapshot = read_public_snapshot(self.store)
        self.assertEqual(len(snapshot), 50)
        self.assertEqual(snapshot[0]["id"], "base-0")

    def test_save_revision_conflict(self):
        seed = self._generate_seed(1)
        self.faq_review.import_questions(seed)
        drafts = self.faq_review.list_drafts()
        draft_id = drafts[0]["id"]
        # Try to save with wrong revision
        with self.assertRaises(Conflict):
            self.faq_review.save(draft_id, {"revision": 999, "question": "new q"}, "tester")

    def test_save_valid_revision(self):
        seed = self._generate_seed(1)
        self.faq_review.import_questions(seed)
        drafts = self.faq_review.list_drafts()
        draft_id = drafts[0]["id"]
        # Save with correct revision
        self.faq_review.save(draft_id, {"revision": 1, "question": "updated question?"}, "tester")
        detail = self.faq_review.detail(draft_id)
        self.assertEqual(detail["question"], "updated question?")
        self.assertEqual(detail["revision"], 2)
        self.assertEqual(len(detail["history"]), 2)
        # History should contain original and updated
        self.assertEqual(detail["history"][0]["question"], "seed question 0?")
        self.assertEqual(detail["history"][1]["question"], "updated question?")

    def test_validation_rejection(self):
        seed = self._generate_seed(1)
        self.faq_review.import_questions(seed)
        drafts = self.faq_review.list_drafts()
        draft_id = drafts[0]["id"]
        # Try to set state='ready' with empty question
        with self.assertRaises(ValueError):
            self.faq_review.save(draft_id, {"revision": 1, "state": "ready", "question": ""}, "tester")
        # Try with invalid source URL
        with self.assertRaises(ValueError):
            self.faq_review.save(draft_id, {"revision": 1, "source_urls": ["http://evil.com"]}, "tester")
        # Try with PII in answer (other than allowed)
        with self.assertRaises(ValueError):
            self.faq_review.save(draft_id, {"revision": 1, "state": "ready", "answer": "My password is secret123"}, "tester")
        # Allowed email/phone should pass
        self.faq_review.save(draft_id, {"revision": 1, "state": "ready", "answer": f"Contact {ALLOWED_EMAIL} or {ALLOWED_PHONE}"}, "tester")
        detail = self.faq_review.detail(draft_id)
        self.assertEqual(detail["state"], "ready")

    def test_migration_idempotence(self):
        # Create another FAQReview instance on same store; should not re-migrate
        faq2 = FAQReview(self.store, self.base_snapshot)
        # No exception, backup should exist from first migration
        backup_dir = self.store.path.parent / "migration-backups"
        backups = list(backup_dir.glob("*.bak"))
        self.assertGreater(len(backups), 0)
        # Check that schema_migrations version is 1
        with self.store.connect() as db:
            version = db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            self.assertEqual(version, 1)

    def test_backup_restore_smoke(self):
        # Backup file should exist and be readable
        backup_dir = self.store.path.parent / "migration-backups"
        backups = list(backup_dir.glob("*.bak"))
        self.assertTrue(len(backups) > 0)
        # Check permissions (on Unix)
        if os.name == 'posix':
            for b in backups:
                mode = b.stat().st_mode & 0o777
                self.assertEqual(mode, 0o600)

    def test_detail_duplicate_candidates(self):
        # Import a draft with same normalized question as a baseline entry
        seed = [{
            "question": "What is the process for building a 0?",
            "answer": "Duplicate answer.",
            "source_urls": ["https://cccbuild.com/faq"],
            "tags": [],
            "source_kind": "draft_file",
            "source_id": "dup-0"
        }]
        self.faq_review.import_questions(seed)
        drafts = self.faq_review.list_drafts()
        draft_id = drafts[0]["id"]
        detail = self.faq_review.detail(draft_id)
        self.assertIn("duplicate_candidates", detail)
        # Should find baseline duplicate
        self.assertTrue(any(c["source"] == "baseline" for c in detail["duplicate_candidates"]))

    def test_json_roundtrip(self):
        """Verify source_urls and tags survive JSON encode/decode cycle."""
        seed = self._generate_seed(1)
        self.faq_review.import_questions(seed)
        drafts = self.faq_review.list_drafts()
        draft_id = drafts[0]["id"]
        detail = self.faq_review.detail(draft_id)
        self.assertEqual(detail["source_urls"], ["https://cccbuild.com/faq"])
        self.assertEqual(detail["tags"], ["test"])
        self.assertIsInstance(detail["source_urls"], list)
        self.assertIsInstance(detail["tags"], list)

    def test_bool_revision(self):
        """revision must be an integer, not bool."""
        seed = self._generate_seed(1)
        self.faq_review.import_questions(seed)
        drafts = self.faq_review.list_drafts()
        draft_id = drafts[0]["id"]
        # bool True should be rejected
        with self.assertRaises(ValueError):
            self.faq_review.save(draft_id, {"revision": True, "question": "q"}, "tester")
        # valid int should work
        self.faq_review.save(draft_id, {"revision": 1, "question": "q"}, "tester")

    def test_unknown_field(self):
        """Passing unknown fields must raise ValueError."""
        seed = self._generate_seed(1)
        self.faq_review.import_questions(seed)
        drafts = self.faq_review.list_drafts()
        draft_id = drafts[0]["id"]
        with self.assertRaises(ValueError):
            self.faq_review.save(draft_id, {"revision": 1, "extra_field": "oops"}, "tester")

    def test_encoded_private_url(self):
        """URLs with percent-encoded private path segments must be rejected."""
        seed = self._generate_seed(1)
        self.faq_review.import_questions(seed)
        drafts = self.faq_review.list_drafts()
        draft_id = drafts[0]["id"]
        # %64 = 'd', so %64ashboard -> dashboard
        bad_url = "https://cccbuild.com/%64ashboard"
        with self.assertRaises(ValueError):
            self.faq_review.save(draft_id, {"revision": 1, "source_urls": [bad_url]}, "tester")
        # Also with encoded separator %2F -> /
        bad_url2 = "https://cccbuild.com/pub%2Fstatic"
        with self.assertRaises(ValueError):
            self.faq_review.save(draft_id, {"revision": 1, "source_urls": [bad_url2]}, "tester")

    def test_missing_ready_sources(self):
        """Setting state='ready' without at least one valid source_url must fail."""
        seed = self._generate_seed(1)
        self.faq_review.import_questions(seed)
        drafts = self.faq_review.list_drafts()
        draft_id = drafts[0]["id"]
        # Provide empty source_urls to trigger missing-source error
        with self.assertRaises(ValueError):
            self.faq_review.save(draft_id, {"revision": 1, "state": "ready", "question": "Q?", "answer": "A.", "source_urls": []}, "tester")

    def test_published_save_bypass(self):
        """Saving with state='published' must be rejected, and editing a published draft must be rejected."""
        seed = self._generate_seed(1)
        self.faq_review.import_questions(seed)
        drafts = self.faq_review.list_drafts()
        draft_id = drafts[0]["id"]
        # Attempt to directly set state='published' via save
        with self.assertRaises(ValueError):
            self.faq_review.save(draft_id, {"revision": 1, "state": "published"}, "tester")
        # Manually set the draft state to 'published' in DB (bypassing save) to simulate
        with self.store.transaction() as db:
            db.execute("UPDATE faq_drafts SET state='published' WHERE id=?", (draft_id,))
        # Now try to edit the published draft
        with self.assertRaises(ValueError):
            self.faq_review.save(draft_id, {"revision": 1, "question": "changed"}, "tester")

    def test_wal_backup_restore(self):
        """Backup created by _backup_db must be a valid SQLite DB with the baseline row."""
        # Trigger a fresh backup after initialization so that baseline is included
        self.faq_review._backup_db()
        backup_dir = self.store.path.parent / "migration-backups"
        backups = sorted(backup_dir.glob("*.bak"), key=lambda p: p.stat().st_mtime, reverse=True)
        self.assertTrue(len(backups) > 0)
        backup_path = backups[0]
        # Open backup and query the release history
        conn = sqlite3.connect(str(backup_path))
        try:
            cursor = conn.execute("SELECT snapshot FROM faq_release_history ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            snapshot = json.loads(row[0])
            self.assertEqual(len(snapshot), 50)
            self.assertEqual(snapshot[0]["id"], "base-0")
        finally:
            conn.close()

if __name__ == "__main__":
    unittest.main()

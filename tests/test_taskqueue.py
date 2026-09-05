"""Tests for the FIFO export queue and per-recording locking."""

from __future__ import annotations

import unittest

from steam_exporter.taskqueue import ExportTask, TaskQueue


def task(appid, game, *folders):
    return ExportTask(appid=appid, game=game, recordings=list(folders), paths=[rf"D:\V\{f}" for f in folders])


class TaskQueueTests(unittest.TestCase):
    def setUp(self):
        self.queue = TaskQueue()

    def test_lock_paths_cover_running_and_pending(self):
        self.queue.running = task("620", "Portal", "bg_620_a")
        self.queue.enqueue(task("440", "TF2", "bg_440_a"))
        self.queue.enqueue(task("220", "HL2", "bg_220_a"))
        self.assertEqual(
            self.queue.lock_paths(),
            {r"D:\V\bg_620_a", r"D:\V\bg_440_a", r"D:\V\bg_220_a"},
        )

    def test_enqueue_rejects_tasks_whose_recordings_are_all_locked(self):
        self.queue.enqueue(task("620", "Portal", "bg_620_a"))
        self.assertFalse(self.queue.enqueue(task("620", "Portal", "bg_620_a")))

    def test_same_game_with_disjoint_recordings_can_be_queued(self):
        self.assertTrue(self.queue.enqueue(task("620", "Portal", "bg_620_a")))
        self.assertTrue(self.queue.enqueue(task("620", "Portal", "bg_620_b")))
        self.assertEqual(len(self.queue.pending), 2)

    def test_take_next_is_fifo_and_requires_a_free_slot(self):
        first, second = task("620", "Portal", "bg_620_a"), task("440", "TF2", "bg_440_a")
        self.queue.enqueue(first)
        self.queue.enqueue(second)
        self.assertEqual(self.queue.take_next(), first)
        self.assertIsNone(self.queue.take_next())  # slot occupied
        self.queue.finish()
        self.assertEqual(self.queue.take_next(), second)

    def test_remove_game_only_touches_pending_tasks_of_that_game(self):
        self.queue.enqueue(task("620", "Portal", "bg_620_a"))
        self.queue.enqueue(task("440", "TF2", "bg_440_a"))
        self.queue.enqueue(task("620", "Portal", "bg_620_b"))
        self.queue.running = task("620", "Portal", "bg_620_c")
        removed = self.queue.remove_game("620")
        self.assertEqual(removed, 2)
        self.assertEqual([t.appid for t in self.queue.pending], ["440"])
        self.assertIsNotNone(self.queue.running)

    def test_finish_and_clear_reset_state(self):
        self.queue.enqueue(task("620", "Portal", "bg_620_a"))
        self.queue.take_next()
        self.queue.finish()
        self.assertIsNone(self.queue.running)
        self.queue.clear()
        self.assertEqual(self.queue.pending, [])
        self.assertEqual(self.queue.lock_paths(), set())


if __name__ == "__main__":
    unittest.main()

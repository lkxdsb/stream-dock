import multiprocessing
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fetchers.errors import MediaProbeError
from fetchers.probe_worker import probe_with_budget


def stalled_probe_child(conn, *_args):
    time.sleep(10)
    conn.close()


def inspect_child_task_store(conn):
    from app import task_store
    conn.send(task_store.storage_path is None)
    conn.close()


class ProbeBudgetTests(unittest.TestCase):
    def test_spawned_app_import_does_not_recover_live_tasks(self):
        from tasks.models import TaskKind, TaskStatus
        from tasks.sqlite_store import SQLiteTaskStore
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tasks.sqlite3'
            store = SQLiteTaskStore(path)
            task = store.create(kind=TaskKind.MEDIA, title='active fixture', payload={})
            store.update(task.id, status=TaskStatus.RUNNING)
            ctx = multiprocessing.get_context('spawn')
            receiver, sender = ctx.Pipe(duplex=False)
            child = ctx.Process(target=inspect_child_task_store, args=(sender,))
            try:
                with patch.dict(os.environ, {'STREAMDOCK_TASK_STORAGE_PATH': str(path)}):
                    child.start()
                sender.close()
                self.assertTrue(receiver.poll(15))
                self.assertTrue(receiver.recv())
                child.join(5)
                self.assertEqual(child.exitcode, 0)
                self.assertEqual(store.get(task.id).status, TaskStatus.RUNNING)
            finally:
                if child.is_alive():
                    child.terminate()
                    child.join(5)
                receiver.close()

    def test_actual_stalled_subprocess_is_terminated_within_budget(self):
        before = {child.pid for child in multiprocessing.active_children()}
        started = time.monotonic()
        with patch('fetchers.probe_worker._probe_child', stalled_probe_child):
            with self.assertRaises(MediaProbeError) as caught:
                probe_with_budget('https://v.douyin.com/stalled-fixture/', timeout_ms=350)
        self.assertEqual(caught.exception.code, 'network_timeout')
        self.assertLess(time.monotonic() - started, 4)
        self.assertEqual({child.pid for child in multiprocessing.active_children()} - before, set())


if __name__ == '__main__':
    unittest.main()

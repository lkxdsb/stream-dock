from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import httpx

# Importing app in tests must not touch ~/.streamdock/tasks.json.
os.environ['STREAMDOCK_TASK_STORAGE_PATH'] = ''

from app import app
from pdf_engine.models import PdfParseMode
from pdf_engine.providers.mineru import MinerUProvider
from pdf_engine.service import analyze_pdf
from pdf_engine.quality import evaluate_pdf_result
from tasks.pdf_queue import PdfQueue
from tasks.store import TaskStore
from tasks.models import TaskStatus


class PdfEngineTests(unittest.IsolatedAsyncioTestCase):
    def test_invalid_pdf_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'bad.pdf'
            path.write_text('not a pdf')
            with self.assertRaises(ValueError):
                analyze_pdf(path)

    def test_provider_health_is_safe_when_engine_missing(self):
        health = MinerUProvider(executable='/missing/mineru').health()
        self.assertFalse(health['available'])
        self.assertEqual(health['provider'], 'local-document-engine')

    async def test_pdf_page_and_health_endpoint(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            page = await client.get('/pdf')
            health = await client.get('/api/pdf/health')
        self.assertEqual(page.status_code, 200)
        self.assertIn('PDF 智能解析', page.text)
        self.assertIn('aria-label="搜索 PDF 任务"', page.text)
        self.assertEqual(health.status_code, 200)
        self.assertIn('available', health.json())

    def test_pdf_task_list_supports_single_delete_and_filtered_empty_state(self):
        script = Path('static/js/pdf.js').read_text(encoding='utf-8')
        self.assertIn('data-delete-pdf-task', script)
        self.assertIn('PDF 任务记录已删除', script)
        self.assertIn('没有符合条件的 PDF 任务。', script)

    async def test_pdf_analyze_rejects_non_pdf_upload(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.post('/api/pdf/analyze', files={'file': ('notes.txt', b'hello', 'text/plain')})
        self.assertEqual(response.status_code, 400)

    def test_pdf_quality_report_reads_markdown_and_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'result.md').write_text('# Title\nUseful content', encoding='utf-8')
            (root / 'result.json').write_text('{"ok": true}', encoding='utf-8')
            quality = evaluate_pdf_result(root)
        self.assertTrue(quality['valid'])
        self.assertEqual(quality['score'], 100)

    def test_pdf_queue_completes_and_cleans_uploaded_input(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / 'input.pdf'
            source.write_bytes(b'%PDF-test')
            store = TaskStore(storage_path=None)
            queue = PdfQueue(store, lambda payload: {'success': True, 'outputPath': payload['outputPath']})
            task_data = queue.submit({'filename': 'input.pdf', 'inputPath': str(source), 'outputPath': temp_dir, 'mode': 'fast'})
            import time
            deadline = time.time() + 2
            task = store.get(task_data['id'])
            while task and task.status not in {TaskStatus.COMPLETED, TaskStatus.FAILED} and time.time() < deadline:
                time.sleep(.02)
                task = store.get(task_data['id'])
            self.assertEqual(task.status, TaskStatus.COMPLETED)
            self.assertFalse(source.exists())

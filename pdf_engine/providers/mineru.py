from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from pdf_engine.models import PdfParseMode, PdfParseResult


class MinerUProvider:
    name = 'local-document-engine'

    def __init__(self, executable: str | None = None, timeout_seconds: int | None = None):
        configured = executable or os.getenv('STREAMDOCK_MINERU_EXECUTABLE')
        isolated = '/opt/anaconda3/envs/streamdock-mineru/bin/mineru'
        self.executable = configured or (isolated if Path(isolated).exists() else None) or shutil.which('mineru') or isolated
        self.timeout_seconds = timeout_seconds or int(os.getenv('STREAMDOCK_PDF_TIMEOUT_SECONDS', '900'))

    def health(self) -> dict[str, object]:
        path = Path(self.executable)
        available = path.exists() and os.access(path, os.X_OK)
        detail = str(path) if available else '未安装独立 PDF 解析环境'
        version = None
        if available:
            try:
                version_result = subprocess.run([str(path), '--version'], capture_output=True, text=True, timeout=15)
                version = (version_result.stdout or version_result.stderr).strip() or None
            except (OSError, subprocess.TimeoutExpired):
                pass
        return {
            'available': available,
            'provider': self.name,
            'detail': detail,
            'executable': str(path),
            'version': version,
            'pipelineAvailable': available,
            'preciseModelReady': any((Path.home() / '.cache' / 'huggingface' / 'hub').glob('models--opendatalab--MinerU*')),
        }

    def _backend_for_mode(self, mode: PdfParseMode) -> str:
        return {
            PdfParseMode.AUTO: 'pipeline',
            PdfParseMode.FAST: 'pipeline',
            PdfParseMode.OCR: 'pipeline',
            PdfParseMode.PRECISE: 'hybrid-engine',
        }[mode]

    def parse(
        self,
        input_path: Path,
        output_dir: Path,
        mode: PdfParseMode,
        process_callback: Callable[[subprocess.Popen[str]], None] | None = None,
    ) -> PdfParseResult:
        health = self.health()
        if not health['available']:
            raise RuntimeError(str(health['detail']))
        output_dir.mkdir(parents=True, exist_ok=True)
        backend = self._backend_for_mode(mode)
        command = [self.executable, '-p', str(input_path), '-o', str(output_dir), '-b', backend]
        if mode == PdfParseMode.FAST:
            command.extend(['-m', 'txt'])
        elif mode == PdfParseMode.OCR:
            command.extend(['-m', 'ocr'])
        elif mode == PdfParseMode.PRECISE:
            command.extend(['--effort', 'high'])
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        if process_callback:
            process_callback(process)
        try:
            stdout, stderr = process.communicate(timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            raise RuntimeError(f'PDF 解析超时，已停止任务（{self.timeout_seconds} 秒）') from exc
        if process.returncode != 0:
            message = (stderr or stdout or 'PDF 解析失败').strip()
            raise RuntimeError(message[-1000:])

        files = sorted(str(path) for path in output_dir.rglob('*') if path.is_file())
        metadata = {'backend': backend, 'stdoutTail': stdout[-1000:]}
        manifest = output_dir / 'streamdock-result.json'
        manifest.write_text(json.dumps({'files': files, **metadata}, ensure_ascii=False, indent=2), encoding='utf-8')
        files.append(str(manifest))
        return PdfParseResult(self.name, mode, str(output_dir), files, metadata)

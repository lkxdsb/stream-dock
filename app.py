from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / 'templates'
STATIC_DIR = BASE_DIR / 'static'
SCRIPT_PATH = BASE_DIR / 'douyin_fetch.py'
OUTPUT_FILE_PATTERN = re.compile(r"output file:\s*(.+)$")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app = FastAPI(title='Douyin Local Fetch UI')
app.mount('/static', StaticFiles(directory=str(STATIC_DIR)), name='static')


class FetchRequest(BaseModel):
    link: str = Field(min_length=1)
    outputPath: str = Field(min_length=1)
    outputType: str = Field(pattern=r'^(m4a|mp3|mp4)$')


def extract_output_file(stdout: str) -> str | None:
    for line in stdout.splitlines():
        match = OUTPUT_FILE_PATTERN.search(line)
        if match:
            return match.group(1).strip()
    return None


@app.get('/', response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        'index.html',
        {
            'request': request,
            'title': '抖音本地解析工具',
        },
    )


@app.post('/api/fetch')
def fetch(payload: FetchRequest):
    command = [
        sys.executable,
        str(SCRIPT_PATH),
        '--link', payload.link,
        '--outputPath', payload.outputPath,
        '--outputType', payload.outputType,
    ]
    completed = subprocess.run(
        command,
        cwd=str(BASE_DIR),
        text=True,
        capture_output=True,
    )
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    output_file = extract_output_file(stdout)

    success = completed.returncode == 0
    body = {
        'success': success,
        'stdout': stdout,
        'stderr': stderr,
        'returncode': completed.returncode,
        'outputPath': output_file,
    }
    if not success:
        body['error'] = stderr or stdout or 'Unknown execution error'
    return JSONResponse(body)

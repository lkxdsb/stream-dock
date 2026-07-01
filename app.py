from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / 'templates'

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app = FastAPI(title='Douyin Local Fetch UI')


@app.get('/', response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name='index.html',
        context={'title': 'Douyin Local Fetch UI'},
    )

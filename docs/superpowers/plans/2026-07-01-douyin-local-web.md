# Douyin Local Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local website that accepts `link`, `outputPath`, and `outputType`, then calls `douyin_fetch.py` and shows logs plus the final output path.

**Architecture:** Use FastAPI as a thin local backend and keep the existing `douyin_fetch.py` as the execution engine. Use a small static frontend with HTML/CSS/JS that POSTs to `/api/fetch` and renders the result.

**Tech Stack:** Python 3.11, FastAPI, Uvicorn, subprocess, HTML, CSS, JavaScript

---

### Task 1: Add backend skeleton and page serving

**Files:**
- Create: `/Users/hjjtongxue/Documents/视频解析工具/app.py`
- Create: `/Users/hjjtongxue/Documents/视频解析工具/templates/index.html`
- Test: FastAPI import and root route

- [ ] **Step 1: Write the failing test**
Run:
```bash
cd /Users/hjjtongxue/Documents/视频解析工具
source $(conda info --base)/etc/profile.d/conda.sh
conda activate jj
python - <<'PY'
from app import app
PY
```
Expected before implementation: import fails because `app.py` does not exist.

- [ ] **Step 2: Run test to verify it fails**
Run the command above and confirm it fails with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**
Create `app.py` with a FastAPI app and `GET /` route serving `templates/index.html`.
Create a minimal `templates/index.html` page with a title and placeholder body.

- [ ] **Step 4: Run test to verify it passes**
Run:
```bash
cd /Users/hjjtongxue/Documents/视频解析工具
source $(conda info --base)/etc/profile.d/conda.sh
conda activate jj
python - <<'PY'
from app import app
print(app.title)
PY
```
Expected: prints the FastAPI title string.

- [ ] **Step 5: Commit**
```bash
git add app.py templates/index.html
git commit -m "feat: add local web backend skeleton"
```

### Task 2: Add fetch API that executes douyin_fetch.py

**Files:**
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/app.py`
- Test: API invocation through FastAPI test client

- [ ] **Step 1: Write the failing test**
Run:
```bash
cd /Users/hjjtongxue/Documents/视频解析工具
source $(conda info --base)/etc/profile.d/conda.sh
conda activate jj
python - <<'PY'
from fastapi.testclient import TestClient
from app import app
client = TestClient(app)
resp = client.post('/api/fetch', json={'link':'x','outputPath':'/tmp','outputType':'mp3'})
print(resp.status_code)
PY
```
Expected before implementation: returns 404 because the API does not exist.

- [ ] **Step 2: Run test to verify it fails**
Run the command above and confirm `404`.

- [ ] **Step 3: Write minimal implementation**
Add request model validation and `/api/fetch` endpoint. The endpoint should run `douyin_fetch.py` via subprocess and return `success/stdout/stderr/outputPath/error`.

- [ ] **Step 4: Run test to verify it passes**
Run a test client request with missing or invalid values and confirm the API returns validation or execution errors in JSON rather than 404.

- [ ] **Step 5: Commit**
```bash
git add app.py
git commit -m "feat: add fetch api endpoint"
```

### Task 3: Add frontend form and JS submission

**Files:**
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/templates/index.html`
- Create: `/Users/hjjtongxue/Documents/视频解析工具/static/app.js`
- Create: `/Users/hjjtongxue/Documents/视频解析工具/static/style.css`
- Modify: `/Users/hjjtongxue/Documents/视频解析工具/app.py`
- Test: browser open and API call from page

- [ ] **Step 1: Write the failing test**
Open the page and confirm there is no usable form or frontend behavior yet.

- [ ] **Step 2: Run test to verify it fails**
Start the server and inspect `http://127.0.0.1:8000`.
Expected: no working input form or no API wiring.

- [ ] **Step 3: Write minimal implementation**
Add:
- form fields for `link`, `outputPath`, `outputType`
- a submit button
- a log output block
- a result block
- JS to call `/api/fetch` and render response
- CSS for a clean local-tool layout
- static file mounting in FastAPI

- [ ] **Step 4: Run test to verify it passes**
Start the server, open the page, submit one valid sample, and confirm the page renders logs and output path.

- [ ] **Step 5: Commit**
```bash
git add app.py templates/index.html static/app.js static/style.css
git commit -m "feat: add local web frontend"
```

### Task 4: Final verification with real samples

**Files:**
- Verify existing files only

- [ ] **Step 1: Write the failing test**
Use one sample with audio stream and one sample with video-only stream.

- [ ] **Step 2: Run test to verify behavior before final polish**
Run both samples through the UI and note any missing status messaging or broken display.

- [ ] **Step 3: Write minimal implementation**
If needed, adjust frontend/backed response formatting so success and failure are clearly visible.

- [ ] **Step 4: Run test to verify it passes**
Verify:
```bash
source $(conda info --base)/etc/profile.d/conda.sh
conda activate jj
uvicorn app:app --reload
```
Then use the page to confirm:
- sample A produces output
- sample B produces output
- page shows logs and final file path

- [ ] **Step 5: Commit**
```bash
git add app.py templates/index.html static/app.js static/style.css
git commit -m "feat: polish local web workflow"
```

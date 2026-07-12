#!/bin/zsh
set -euo pipefail

PROJECT_DIR="${0:A:h}"
PORT="${STREAMDOCK_PORT:-8002}"
URL="http://127.0.0.1:${PORT}"
PYTHON="${STREAMDOCK_PYTHON:-/opt/anaconda3/envs/jj/bin/python}"

cd "$PROJECT_DIR"

if [[ ! -x "$PYTHON" ]]; then
  if command -v conda >/dev/null 2>&1; then
    PYTHON="$(conda run -n jj python -c 'import sys; print(sys.executable)')"
  else
    echo "未找到 jj 环境。请设置 STREAMDOCK_PYTHON 后重试。"
    read -k 1 "?按任意键退出..."
    exit 1
  fi
fi

if lsof -ti "tcp:${PORT}" >/dev/null 2>&1; then
  if curl -fsS "${URL}/api/health" >/dev/null 2>&1; then
    echo "StreamDock 已在运行：${URL}"
    open "$URL"
    exit 0
  fi
  echo "端口 ${PORT} 已被其他程序占用，请关闭占用程序或设置 STREAMDOCK_PORT。"
  read -k 1 "?按任意键退出..."
  exit 1
fi

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]] && kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM HUP

echo "正在启动 StreamDock..."
"$PYTHON" -m uvicorn app:app --host 127.0.0.1 --port "$PORT" &
SERVER_PID=$!

for _ in {1..40}; do
  if curl -fsS "$URL/api/health" >/dev/null 2>&1; then
    echo "StreamDock 已启动：${URL}"
    open "$URL"
    wait "$SERVER_PID"
    exit $?
  fi
  sleep 0.25
done

echo "启动超时，请检查上方日志。"
exit 1

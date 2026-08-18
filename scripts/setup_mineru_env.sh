#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="${STREAMDOCK_MINERU_ENV:-streamdock-mineru}"
if ! command -v conda >/dev/null 2>&1; then
  echo 'ERROR: conda is not installed or not on PATH' >&2
  exit 1
fi

if [[ "${CONDA_PREFIX:-}" == */envs/* ]]; then
  CONDA_BASE="${CONDA_PREFIX%/envs/*}"
else
  CONDA_BASE="$(conda info --base)"
fi
ENV_PATH="${CONDA_BASE}/envs/${ENV_NAME}"

if ! conda env list | awk '{print $1}' | grep -qx "${ENV_NAME}"; then
  conda create -n "${ENV_NAME}" python=3.11 -y
fi

"${ENV_PATH}/bin/python" -m pip install -U uv
"${ENV_PATH}/bin/python" -m uv pip install 'mineru[pipeline]' six accelerate

echo "MinerU environment ready: ${ENV_PATH}"
echo "Executable: ${ENV_PATH}/bin/mineru"

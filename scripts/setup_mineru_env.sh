#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="${STREAMDOCK_MINERU_ENV:-streamdock-mineru}"
ENV_PATH="${CONDA_PREFIX%/envs/*}/envs/${ENV_NAME}"
if [[ -z "${CONDA_PREFIX:-}" || "${CONDA_PREFIX}" != */envs/* ]]; then
  ENV_PATH="/opt/anaconda3/envs/${ENV_NAME}"
fi

if ! conda env list | awk '{print $1}' | grep -qx "${ENV_NAME}"; then
  conda create -n "${ENV_NAME}" python=3.11 -y
fi

"${ENV_PATH}/bin/python" -m pip install -U uv
"${ENV_PATH}/bin/python" -m uv pip install 'mineru[pipeline]' six accelerate

echo "MinerU environment ready: ${ENV_PATH}"
echo "Executable: ${ENV_PATH}/bin/mineru"

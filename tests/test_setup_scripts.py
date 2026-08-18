from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile


def test_setup_mineru_env_works_without_active_conda_environment():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fake_bin = root / 'bin'
        conda_base = root / 'conda'
        env_name = 'test-mineru'
        env_bin = conda_base / 'envs' / env_name / 'bin'
        calls = root / 'python-calls.log'
        fake_bin.mkdir()
        env_bin.mkdir(parents=True)

        conda = fake_bin / 'conda'
        conda.write_text(
            '#!/usr/bin/env bash\n'
            'if [[ "$1 $2" == "info --base" ]]; then\n'
            f'  echo "{conda_base}"\n'
            'elif [[ "$1 $2" == "env list" ]]; then\n'
            f'  echo "{env_name} * {conda_base}/envs/{env_name}"\n'
            'else\n'
            '  exit 2\n'
            'fi\n',
            encoding='utf-8',
        )
        conda.chmod(0o755)

        python = env_bin / 'python'
        python.write_text(
            '#!/usr/bin/env bash\n'
            f'printf "%s\\n" "$*" >> "{calls}"\n',
            encoding='utf-8',
        )
        python.chmod(0o755)

        env = os.environ.copy()
        env.pop('CONDA_PREFIX', None)
        env['STREAMDOCK_MINERU_ENV'] = env_name
        env['PATH'] = f'{fake_bin}:{env["PATH"]}'
        completed = subprocess.run(
            ['bash', 'scripts/setup_mineru_env.sh'],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        assert completed.returncode == 0, completed.stderr
        assert f'MinerU environment ready: {conda_base}/envs/{env_name}' in completed.stdout
        assert calls.read_text(encoding='utf-8').splitlines() == [
            '-m pip install -U uv',
            "-m uv pip install mineru[pipeline] six accelerate",
        ]


def load_tests(loader, tests, pattern):
    import unittest

    suite = unittest.TestSuite()
    suite.addTest(unittest.FunctionTestCase(test_setup_mineru_env_works_without_active_conda_environment))
    return suite

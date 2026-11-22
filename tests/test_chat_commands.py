import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which('node'), reason='node 없음')
def test_chat_command_parser():
    script = Path(__file__).parent / 'js' / 'chat_commands.test.js'
    done = subprocess.run(['node', str(script)], capture_output=True, text=True, encoding='utf-8')
    assert done.returncode == 0, done.stdout + done.stderr

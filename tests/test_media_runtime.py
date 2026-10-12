import subprocess
import time

import pytest

from studio import media


@pytest.mark.parametrize('reason', ['cancel', 'timeout'])
def test_ffmpeg_interrupt_reaps_process(tmp_path, monkeypatch, reason):
    processes = []
    real_popen = subprocess.Popen

    def launch(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(media.subprocess, 'Popen', launch)
    if reason == 'timeout':
        monkeypatch.setattr(media, 'JOB_TIMEOUT', .2)
    started = time.monotonic()
    with pytest.raises(media.Cancelled if reason == 'cancel' else ValueError):
        media.run_ffmpeg(['-re', '-f', 'lavfi', '-i', 'testsrc2=size=16x16:rate=30:duration=5', '-f', 'null', '-'],
                         tmp_path, cancelled=lambda: reason == 'cancel' and time.monotonic() - started > .2)
    assert processes and all(p.poll() is not None for p in processes)
    assert time.monotonic() - started < 8

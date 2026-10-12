"""Create real test media with tones and silence. It intentionally contains no speech."""
import subprocess
import sys
from pathlib import Path

target = Path(sys.argv[1] if len(sys.argv) > 1 else '/tmp/iyoring-sample.mp4')
subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=180x320:rate=30:duration=8',
                '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=8',
                '-af', "volume=enable='between(t,2,4)':volume=0", '-c:v', 'libx264', '-threads', '2',
                '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(target)], check=True)
print(target)

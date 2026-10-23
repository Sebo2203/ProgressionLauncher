"""Run each regression script in a separate process on any supported OS."""
from pathlib import Path
import subprocess
import sys

for test in sorted(Path(__file__).parent.glob('*_smoke.py')):
    if test.name == Path(__file__).name:
        continue
    subprocess.run([sys.executable, str(test)], check=True)

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcai.memory_job import join  # noqa: E402

join(sys.argv[1])
raise SystemExit(subprocess.run(sys.argv[2:], check=False).returncode)

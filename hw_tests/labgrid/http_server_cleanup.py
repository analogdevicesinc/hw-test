import glob
import os
import shutil
import signal
import sys

remote_dir = sys.argv[1]
pid_path = os.path.join(remote_dir, "http.pid")

try:
    with open(pid_path, encoding="ascii") as pid_file:
        pid = int(pid_file.read().strip())
except (FileNotFoundError, ValueError):
    pid = None

if pid is not None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

shutil.rmtree(remote_dir, ignore_errors=True)

# Cleanup all orphaned http directories
for old_dir in glob.glob("/tmp/hw-test-http.*"):
    try:
        shutil.rmtree(old_dir, ignore_errors=True)
    except Exception:
        pass

import os
import subprocess
import sys
import time

remote_dir = sys.argv[1]
log_path = os.path.join(remote_dir, "http.log")
pid_path = os.path.join(remote_dir, "http.pid")

log = open(log_path, "ab", buffering=0)
process = subprocess.Popen(
    ["python3", "-m", "http.server", "--bind", "0.0.0.0"],
    cwd=remote_dir,
    stdin=subprocess.DEVNULL,
    stdout=log,
    stderr=subprocess.STDOUT,
    start_new_session=True,
    close_fds=True,
)
log.close()

with open(pid_path, "w", encoding="ascii") as pid_file:
    pid_file.write(f"{process.pid}\n")

time.sleep(1)
returncode = process.poll()
if returncode is not None:
    with open(log_path, encoding="utf-8", errors="replace") as log_file:
        sys.stderr.write(log_file.read())
    raise SystemExit(returncode or 1)

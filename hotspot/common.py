import logging
import subprocess

log = logging.getLogger(__name__)


def run(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", f"{cmd[0]}: not found"
    if p.returncode != 0:
        log.debug("cmd=%s rc=%s stderr=%s", cmd, p.returncode, (p.stderr or "").strip())
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def tail_file(path, lines=15):
    try:
        with open(path, "r", errors="replace") as fh:
            return "".join(fh.readlines()[-lines:]).strip()
    except OSError:
        return ""

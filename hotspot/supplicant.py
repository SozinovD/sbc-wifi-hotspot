import logging
import os
import subprocess
import time

from .common import tail_file

log = logging.getLogger(__name__)

CTRL_DIR = "/run/wpa_supplicant"

CONF_HEADER = (
    "ctrl_interface=DIR={ctrl} GROUP=0\n"
    "update_config=1\n"
    "country={country}\n"
)


class WpaSupplicant:
    def __init__(self, cfg):
        self.cfg = cfg
        self.conf_path = os.path.join(cfg.data_dir, "wpa_supplicant.conf")
        self.socket_path = os.path.join(CTRL_DIR, cfg.interface)
        self.log_path = os.path.join(cfg.run_dir, "wpa_supplicant.log")
        self.proc = None
        self._log_fh = None

    def ensure_conf(self):
        os.makedirs(self.cfg.data_dir, exist_ok=True)
        if os.path.exists(self.conf_path):
            return
        with open(self.conf_path, "w") as fh:
            fh.write(
                CONF_HEADER.format(ctrl=CTRL_DIR, country=self.cfg.country)
            )
        log.info("created %s", self.conf_path)

    def start(self):
        if self.is_running():
            return True
        self.ensure_conf()
        os.makedirs(CTRL_DIR, exist_ok=True)
        last_err = ""
        for attempt in range(3):
            self._log_fh = open(self.log_path, "ab")
            self.proc = subprocess.Popen(
                ["wpa_supplicant", "-i", self.cfg.interface, "-c", self.conf_path],
                stdout=self._log_fh,
                stderr=subprocess.STDOUT,
            )
            deadline = time.time() + 5
            while time.time() < deadline:
                if os.path.exists(self.socket_path):
                    log.info("wpa_supplicant started (pid %s)", self.proc.pid)
                    return True
                if self.proc.poll() is not None:
                    break
                time.sleep(0.2)
            last_err = tail_file(self.log_path)
            log.warning(
                "wpa_supplicant start attempt %d failed: %s", attempt + 1, last_err
            )
            self._close_fh()
            time.sleep(2)
        raise RuntimeError(f"wpa_supplicant failed to start: {last_err}")

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        proc, fh = self.proc, self._log_fh
        self.proc, self._log_fh = None, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if fh is not None:
            fh.close()
        try:
            os.remove(self.socket_path)
        except OSError:
            pass

    def _close_fh(self):
        fh, self._log_fh = self._log_fh, None
        if fh is not None:
            fh.close()

    def cli(self, *args, timeout=15):
        cmd = [
            "wpa_cli",
            "-p",
            CTRL_DIR,
            "-i",
            self.cfg.interface,
            *[str(a) for a in args],
        ]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return 124, []
        lines = [ln for ln in (p.stdout or "").splitlines() if ln.strip()]
        return p.returncode, lines

    def _ok(self, *args):
        rc, lines = self.cli(*args)
        return rc == 0 and bool(lines) and lines[-1] == "OK"

    def status(self):
        rc, lines = self.cli("status")
        st = {}
        for line in lines:
            if "=" in line:
                key, value = line.split("=", 1)
                st[key.strip()] = value.strip()
        return st

    def state(self):
        return self.status().get("wpa_state")

    def wait_completed(self, timeout, stop=None):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if stop is not None and stop.is_set():
                return None
            if not self.is_running():
                return None
            st = self.status()
            if st.get("wpa_state") == "COMPLETED":
                return st
            time.sleep(0.5)
        return None

    def known_count(self):
        try:
            with open(self.conf_path, "r") as fh:
                text = fh.read()
        except OSError:
            return 0
        return sum(1 for ln in text.splitlines() if ln.strip().startswith("network={"))

    @staticmethod
    def _quote(value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    def connect_new(self, ssid, password):
        self._ok("disable_network", "all")
        rc, lines = self.cli("add_network")
        if rc != 0 or not lines:
            log.error("add_network failed: %s", lines)
            return None
        try:
            nid = int(lines[-1])
        except ValueError:
            return None
        ok = self._ok("set_network", nid, "ssid", self._quote(ssid))
        if password:
            ok = ok and self._ok("set_network", nid, "psk", self._quote(password))
        else:
            ok = ok and self._ok("set_network", nid, "key_mgmt", "NONE")
        ok = ok and self._ok("set_network", nid, "scan_ssid", "1")
        if not ok:
            log.error("set_network failed for network %s", nid)
            return None
        if not self._ok("enable_network", nid):
            return None
        return nid

    def enable_all(self):
        rc, lines = self.cli("list_networks")
        for line in lines[1:]:
            parts = line.split()
            if parts:
                self._ok("enable_network", parts[0])
        self.persist()

    def persist(self):
        return self._ok("save_config")

    def forget(self, nid):
        self._ok("remove_network", nid)
        self.enable_all()

    def disconnect(self):
        self._ok("disconnect")

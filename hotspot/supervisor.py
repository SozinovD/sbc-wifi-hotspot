import logging
import os
import queue
import threading
import time

from waitress.server import create_server

from . import netif, scanner
from .ap import ApManager
from .common import run
from .connectivity import has_internet, wait_internet
from .portal import create_app
from .supplicant import WpaSupplicant

log = logging.getLogger(__name__)

SCAN_CACHE_TTL = 5


class Supervisor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.supplicant = WpaSupplicant(cfg)
        self.ap = ApManager(cfg)
        self._requests = queue.Queue()
        self._lock = threading.Lock()
        self._last_attempt = None
        self._pending = False
        self._stop = threading.Event()
        self._portal_server = None
        self._scan_cache = ([], 0.0)

    def shutdown(self):
        self._stop.set()

    def request_connect(self, ssid, password):
        with self._lock:
            if self._pending:
                return False
            self._pending = True
            self._last_attempt = {
                "ssid": ssid,
                "result": "in_progress",
                "reason": None,
                "ts": time.time(),
            }
        self._requests.put((ssid, password))
        return True

    def _finish_attempt(self, result, reason=None):
        with self._lock:
            self._pending = False
            if self._last_attempt is not None:
                self._last_attempt["result"] = result
                self._last_attempt["reason"] = reason

    def last_attempt(self):
        with self._lock:
            return dict(self._last_attempt) if self._last_attempt else None

    def api_scan(self):
        nets, ts = self._scan_cache
        if time.time() - ts < SCAN_CACHE_TTL:
            return nets
        nets = scanner.iw_scan(self.cfg.interface)
        self._scan_cache = (nets, time.time())
        return nets

    def run_forever(self):
        os.makedirs(self.cfg.run_dir, exist_ok=True)
        self._warn_nm()
        while not self._stop.is_set():
            try:
                self._cycle()
            except Exception:
                log.exception("cycle failed, restarting in 5s")
                self._cleanup()
                self._stop.wait(5)
        self._cleanup()

    def _cycle(self):
        if self._try_client():
            reason = self._client_loop()
            log.info("client mode ended: %s", reason)
            if reason == "shutdown":
                return
        self._ap_loop()

    def _try_client(self):
        if not self.supplicant.is_running():
            if self.supplicant.known_count() == 0:
                log.info("no known networks, starting AP")
                return False
            if not self.supplicant.start():
                return False
        if self.supplicant.known_count() == 0:
            self.supplicant.stop()
            return False
        st = self.supplicant.wait_completed(
            self.cfg.client_wait_timeout, stop=self._stop
        )
        if st is None:
            log.info("no known network connected within %ss", self.cfg.client_wait_timeout)
            self.supplicant.stop()
            return False
        log.info("connected to %r, ip=%s", st.get("ssid"), st.get("ip_addr", "?"))
        self._dhcp()
        return True

    def _client_loop(self):
        losses = 0
        while not self._stop.is_set():
            self._stop.wait(self.cfg.monitor_interval)
            if self._stop.is_set():
                return "shutdown"
            if not self.supplicant.is_running():
                return "supplicant_died"
            st = self.supplicant.status()
            if st.get("wpa_state") != "COMPLETED":
                return "disconnected"
            if has_internet(self.cfg.internet_urls, self.cfg.internet_timeout):
                losses = 0
                continue
            losses += 1
            log.warning(
                "no internet (%d/%d)", losses, self.cfg.internet_loss_retries
            )
            if losses >= self.cfg.internet_loss_retries:
                return "no_internet"
        return "shutdown"

    def _ap_loop(self):
        while not self._stop.is_set():
            self._dhcp_release()
            self.supplicant.stop()
            self._drain_requests()
            self.ap.start()
            self._start_portal()
            outcome = self._serve_portal()
            self._stop_portal()
            self.ap.stop()
            if outcome in ("stop", "recheck"):
                return
            ssid, password = outcome
            if self._attempt_connect(ssid, password):
                return
            log.info("attempt failed, restarting AP")

    def _serve_portal(self):
        started = time.time()
        while not self._stop.is_set():
            if not self.ap.is_running():
                raise RuntimeError(
                    "AP processes died (see logs in %s)" % self.cfg.run_dir
                )
            try:
                item = self._requests.get(timeout=1.0)
            except queue.Empty:
                interval = self.cfg.ap_client_retry_interval
                known = self.supplicant.known_count()
                if interval > 0 and known > 0 and time.time() - started > interval:
                    return "recheck"
                continue
            return item
        return "stop"

    def _attempt_connect(self, ssid, password):
        try:
            if not self.supplicant.start():
                self._finish_attempt("fail", "не удалось запустить wpa_supplicant")
                return False
            net_id = self.supplicant.connect_new(ssid, password)
            if net_id is None:
                self.supplicant.stop()
                self._finish_attempt("fail", "ошибка конфигурации сети")
                return False
            st = self.supplicant.wait_completed(
                self.cfg.connect_timeout, stop=self._stop
            )
            if st is None:
                self.supplicant.forget(net_id)
                self.supplicant.disconnect()
                self.supplicant.stop()
                self._finish_attempt(
                    "fail", "неверный пароль или сеть недоступна"
                )
                return False
            self._dhcp()
            if not wait_internet(
                self.cfg.internet_urls, self.cfg.internet_timeout, tries=3, delay=5
            ):
                self.supplicant.forget(net_id)
                self.supplicant.disconnect()
                self.supplicant.stop()
                self._finish_attempt("fail", "в сети нет интернета")
                return False
            self.supplicant.enable_all()
            self._finish_attempt("ok")
            log.info("provisioned network %r with internet", ssid)
            return True
        except Exception:
            log.exception("attempt_connect failed")
            self.supplicant.stop()
            self._finish_attempt("fail", "внутренняя ошибка")
            return False

    def _dhcp(self):
        pid = os.path.join(self.cfg.run_dir, "dhclient.pid")
        self._dhcp_release()
        run(
            ["dhclient", "-1", "-q", "-pf", pid, self.cfg.interface],
            timeout=60,
        )
        addr = netif.current_addr(self.cfg.interface)
        if addr:
            log.info("dhcp lease: %s", addr)
        else:
            log.warning("dhcp failed on %s", self.cfg.interface)

    def _dhcp_release(self):
        pid = os.path.join(self.cfg.run_dir, "dhclient.pid")
        if os.path.exists(pid):
            run(["dhclient", "-r", "-q", "-pf", pid, self.cfg.interface], timeout=15)
            try:
                os.remove(pid)
            except OSError:
                pass

    def _drain_requests(self):
        while True:
            try:
                self._requests.get_nowait()
            except queue.Empty:
                break
        with self._lock:
            self._pending = False

    def _start_portal(self):
        app = create_app(self)
        self._portal_server = create_server(
            app,
            listen=f"{self.cfg.ap_ip}:{self.cfg.portal_port}",
            threads=4,
        )
        threading.Thread(
            target=self._portal_server.run, name="portal", daemon=True
        ).start()
        log.info("portal: http://%s/", self.cfg.ap_ip)

    def _stop_portal(self):
        server, self._portal_server = self._portal_server, None
        if server is not None:
            try:
                server.close()
            except Exception:
                log.exception("portal stop failed")

    def _cleanup(self):
        self._stop_portal()
        self.ap.stop()
        self._dhcp_release()
        self.supplicant.stop()

    def _warn_nm(self):
        try:
            rc, out, _ = run(
                ["nmcli", "-t", "-f", "DEVICE,STATE", "device", "status"],
                timeout=10,
            )
        except Exception:
            return
        if rc != 0:
            return
        for line in out.splitlines():
            if line.startswith(self.cfg.interface + ":"):
                log.warning(
                    "NetworkManager управляет интерфейсом %s — конфликт wpa_supplicant. "
                    "Добавьте unmanaged-devices=interface-name:%s в "
                    "/etc/NetworkManager/conf.d/ и перезапустите NetworkManager "
                    "(или запустите scripts/install.sh)",
                    self.cfg.interface,
                    self.cfg.interface,
                )
                return

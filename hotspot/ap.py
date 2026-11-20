import logging
import os
import subprocess
import time

from . import netif
from .common import tail_file

log = logging.getLogger(__name__)

HOSTAPD_CONF = """\
interface={iface}
driver=nl80211
ssid={ssid}
country_code={country}
hw_mode={hw_mode}
channel={channel}
ieee80211n=1
wmm_enabled=1
auth_algs=1
wpa=2
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
wpa_passphrase={passphrase}
macaddr_acl=0
"""

DNSMASQ_CONF = """\
interface={iface}
bind-interfaces
no-resolv
no-hosts
address=/#/{ap_ip}
dhcp-range={dhcp_range}
dhcp-option=6,{ap_ip}
dhcp-authoritative
"""


class ApManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self.hostapd_conf = os.path.join(cfg.run_dir, "hostapd.conf")
        self.dnsmasq_conf = os.path.join(cfg.run_dir, "dnsmasq.conf")
        self.hostapd = None
        self.dnsmasq = None
        self._hostapd_fh = None
        self._dnsmasq_fh = None

    def _write_configs(self):
        with open(self.hostapd_conf, "w") as fh:
            fh.write(
                HOSTAPD_CONF.format(
                    iface=self.cfg.interface,
                    ssid=self.cfg.ap_ssid,
                    country=self.cfg.country,
                    hw_mode=self.cfg.ap_hw_mode,
                    channel=self.cfg.ap_channel,
                    passphrase=self.cfg.ap_passphrase,
                )
            )
        with open(self.dnsmasq_conf, "w") as fh:
            fh.write(
                DNSMASQ_CONF.format(
                    iface=self.cfg.interface,
                    ap_ip=self.cfg.ap_ip,
                    dhcp_range=self.cfg.dhcp_range,
                )
            )

    def start(self):
        os.makedirs(self.cfg.run_dir, exist_ok=True)
        self._write_configs()
        netif.set_ap_addr(self.cfg.interface, self.cfg.ap_ip)

        self._dnsmasq_fh = open(
            os.path.join(self.cfg.run_dir, "dnsmasq.log"), "ab"
        )
        self.dnsmasq = subprocess.Popen(
            [
                "dnsmasq",
                "--conf-file=" + self.dnsmasq_conf,
                "--no-daemon",
                "--pid-file=",
            ],
            stdout=self._dnsmasq_fh,
            stderr=subprocess.STDOUT,
        )
        time.sleep(0.7)
        if self.dnsmasq.poll() is not None:
            err = tail_file(os.path.join(self.cfg.run_dir, "dnsmasq.log"))
            self._close_procs()
            raise RuntimeError(f"dnsmasq failed to start: {err}")

        self._hostapd_fh = open(
            os.path.join(self.cfg.run_dir, "hostapd.log"), "ab"
        )
        self.hostapd = subprocess.Popen(
            ["hostapd", self.hostapd_conf],
            stdout=self._hostapd_fh,
            stderr=subprocess.STDOUT,
        )
        time.sleep(2.5)
        if self.hostapd.poll() is not None:
            err = tail_file(os.path.join(self.cfg.run_dir, "hostapd.log"))
            self._close_procs()
            raise RuntimeError(f"hostapd failed to start: {err}")

        log.info(
            "AP started: ssid=%s ip=%s channel=%s",
            self.cfg.ap_ssid,
            self.cfg.ap_ip,
            self.cfg.ap_channel,
        )

    def is_running(self):
        dnsmasq_ok = self.dnsmasq is not None and self.dnsmasq.poll() is None
        hostapd_ok = self.hostapd is not None and self.hostapd.poll() is None
        return dnsmasq_ok and hostapd_ok

    def _close_procs(self):
        for attr, fh_attr in (
            ("hostapd", "_hostapd_fh"),
            ("dnsmasq", "_dnsmasq_fh"),
        ):
            proc = getattr(self, attr)
            fh = getattr(self, fh_attr)
            setattr(self, attr, None)
            setattr(self, fh_attr, None)
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            if fh is not None:
                fh.close()

    def stop(self):
        self._close_procs()
        netif.flush_addr(self.cfg.interface)
        log.info("AP stopped")

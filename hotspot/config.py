import os
from dataclasses import dataclass

_DEFAULT_URLS = ",".join(
    [
        "http://connectivity-check.ubuntu.com/",
        "http://www.gstatic.com/generate_204",
        "http://detectportal.firefox.com/success.txt",
    ]
)


@dataclass
class Config:
    interface: str
    ap_ssid: str
    ap_passphrase: str
    ap_ip: str
    ap_channel: int
    ap_hw_mode: str
    portal_port: int
    data_dir: str
    run_dir: str
    client_wait_timeout: int
    connect_timeout: int
    scan_wait: float
    internet_timeout: float
    internet_urls: list
    internet_loss_retries: int
    monitor_interval: int
    ap_client_retry_interval: int
    country: str
    log_level: str

    @property
    def dhcp_range(self):
        base = self.ap_ip.rsplit(".", 1)[0]
        return f"{base}.2,{base}.150,255.255.255.0,12h"

    @classmethod
    def from_env(cls):
        env = os.environ
        raw_urls = env.get("INTERNET_CHECK_URLS", "").strip()
        urls = [u.strip() for u in raw_urls.split(",") if u.strip()] or [
            u for u in _DEFAULT_URLS.split(",") if u.strip()
        ]
        cfg = cls(
            interface=env.get("WIFI_INTERFACE", "wlan0"),
            ap_ssid=env.get("AP_SSID", "SBC-Hotspot"),
            ap_passphrase=env.get("AP_PASSPHRASE", "sbc-hotspot"),
            ap_ip=env.get("AP_IP", "192.168.4.1"),
            ap_channel=int(env.get("AP_CHANNEL", "6")),
            ap_hw_mode=env.get("AP_HW_MODE", "g"),
            portal_port=int(env.get("PORTAL_PORT", "80")),
            data_dir=env.get("DATA_DIR", "/data"),
            run_dir=env.get("RUN_DIR", "/run/sbc-wifi-hotspot"),
            client_wait_timeout=int(env.get("CLIENT_WAIT_TIMEOUT", "45")),
            connect_timeout=int(env.get("CONNECT_TIMEOUT", "25")),
            scan_wait=float(env.get("SCAN_WAIT", "4")),
            internet_timeout=float(env.get("INTERNET_TIMEOUT", "5")),
            internet_urls=urls,
            internet_loss_retries=int(env.get("INTERNET_LOSS_RETRIES", "5")),
            monitor_interval=int(env.get("MONITOR_INTERVAL", "30")),
            ap_client_retry_interval=int(env.get("AP_CLIENT_RETRY_INTERVAL", "0")),
            country=env.get("WIFI_COUNTRY", "00"),
            log_level=env.get("LOG_LEVEL", "INFO").upper(),
        )
        if not 8 <= len(cfg.ap_passphrase) <= 63:
            raise ValueError("AP_PASSPHRASE must be 8..63 characters (WPA2 requirement)")
        return cfg

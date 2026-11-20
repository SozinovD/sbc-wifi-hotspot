import logging

from .common import run

log = logging.getLogger(__name__)


def _security_from_flags(flags):
    if "SAE" in flags:
        return "WPA3"
    if "WPA2" in flags or "RSN" in flags:
        return "WPA2"
    if "WPA" in flags:
        return "WPA"
    if "WEP" in flags or "Privacy" in flags:
        return "WEP"
    return "Open"


def _parse_iw(text):
    nets = []
    cur = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("BSS "):
            if cur:
                nets.append(cur)
            bssid = s.split()[1].split("(")[0]
            cur = {"bssid": bssid, "ssid": None, "signal": -100, "freq": 0, "flags": ""}
        elif cur is None:
            continue
        elif s.startswith("SSID: "):
            cur["ssid"] = s[6:] or None
        elif s.startswith("freq:"):
            try:
                cur["freq"] = int(s.split(":")[1])
            except (ValueError, IndexError):
                pass
        elif s.startswith("signal:"):
            try:
                cur["signal"] = int(float(s.split(":")[1].split()[0]))
            except (ValueError, IndexError):
                pass
        elif s.startswith("RSN:"):
            cur["flags"] += "[WPA2]"
        elif s.startswith("WPA:"):
            cur["flags"] += "[WPA]"
        elif s.startswith("capability:") and "Privacy" in s:
            cur["flags"] += "[Privacy]"
    if cur:
        nets.append(cur)
    return nets


def _normalize(items):
    best = {}
    for it in items:
        key = it["ssid"] if it["ssid"] else f"bss:{it['bssid']}"
        prev = best.get(key)
        if prev is None or it["signal"] > prev["signal"]:
            best[key] = it
    result = [
        {
            "ssid": it["ssid"],
            "bssid": it["bssid"],
            "signal": it["signal"],
            "freq": it["freq"],
            "security": _security_from_flags(it["flags"]),
        }
        for it in best.values()
    ]
    result.sort(key=lambda n: n["signal"], reverse=True)
    return result


def iw_scan(interface, timeout=15):
    rc, out, err = run(["iw", "dev", interface, "scan"], timeout=timeout)
    if rc != 0:
        log.warning("iw scan failed: rc=%s err=%s", rc, err)
        return []
    return _normalize(_parse_iw(out))

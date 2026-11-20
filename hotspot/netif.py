import re

from .common import run


def _ip(*args):
    return run(["ip", *args])


def set_ap_addr(iface, ip):
    _ip("addr", "flush", "dev", iface)
    _ip("addr", "add", f"{ip}/24", "dev", iface)
    _ip("link", "set", "dev", iface, "up")


def flush_addr(iface):
    _ip("addr", "flush", "dev", iface)


def current_addr(iface):
    rc, out, _ = _ip("-4", "addr", "show", "dev", iface)
    if rc != 0:
        return None
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
    return m.group(1) if m else None

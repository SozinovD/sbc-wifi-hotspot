import logging
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

_UA = "sbc-wifi-hotspot/0.1"


def _fetch(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read(64)
        return resp.status


def has_internet(urls, timeout):
    def fetch(url):
        try:
            _fetch(url, timeout)
            return True
        except Exception:
            return False

    if not urls:
        return False
    with ThreadPoolExecutor(max_workers=len(urls)) as ex:
        results = [ex.submit(fetch, u) for u in urls]
        return any(f.result() for f in results)


def wait_internet(urls, timeout, tries=3, delay=5):
    for i in range(tries):
        if has_internet(urls, timeout):
            return True
        if i < tries - 1:
            log.info("internet check %d/%d failed, retrying in %ss", i + 1, tries, delay)
            time.sleep(delay)
    return False

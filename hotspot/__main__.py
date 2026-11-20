import logging
import signal

from .config import Config
from .supervisor import Supervisor


def main():
    cfg = Config.from_env()
    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("hotspot")
    log.info(
        "starting sbc-wifi-hotspot %s: iface=%s ap_ssid=%s",
        __import__("hotspot").__version__,
        cfg.interface,
        cfg.ap_ssid,
    )
    supervisor = Supervisor(cfg)

    def _handle(signum, _frame):
        log.info("signal %s received, shutting down", signum)
        supervisor.shutdown()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    supervisor.run_forever()
    log.info("stopped")


if __name__ == "__main__":
    main()

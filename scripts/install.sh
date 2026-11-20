#!/usr/bin/env bash
set -euo pipefail

IFACE="${WIFI_INTERFACE:-wlan0}"
DEST=/opt/sbc-wifi-hotspot
ENV_FILE=/etc/sbc-wifi-hotspot.env
UNIT=/etc/systemd/system/sbc-wifi-hotspot.service

if [ "$(id -u)" -ne 0 ]; then
  echo "Запустите от root: sudo $0" >&2
  exit 1
fi
cd "$(dirname "$0")/.."

echo "==> Установка пакетов"
apt-get update
apt-get install -y hostapd dnsmasq wpasupplicant iw iproute2 isc-dhcp-client \
  python3 python3-venv

echo "==> Отключаем системные сетевые сервисы для Wi-Fi"
systemctl disable --now wpa_supplicant.service 2>/dev/null || true
systemctl disable --now wpa_supplicant@"${IFACE}".service 2>/dev/null || true
systemctl disable --now hostapd.service 2>/dev/null || true
systemctl disable --now dnsmasq.service 2>/dev/null || true

if command -v nmcli >/dev/null 2>&1; then
  echo "==> Исключаем ${IFACE} из NetworkManager"
  mkdir -p /etc/NetworkManager/conf.d
  cat > /etc/NetworkManager/conf.d/10-sbc-wifi-hotspot.conf <<EOF
[keyfile]
unmanaged-devices=interface-name:${IFACE}
EOF
  systemctl reload NetworkManager 2>/dev/null || systemctl restart NetworkManager || true
fi

echo "==> Копируем код в ${DEST}"
mkdir -p "${DEST}"
cp -a hotspot requirements.txt "${DEST}/"

python3 -m venv "${DEST}/venv"
"${DEST}/venv/bin/pip" install --upgrade pip
"${DEST}/venv/bin/pip" install -r "${DEST}/requirements.txt"

if [ ! -f "${ENV_FILE}" ]; then
  echo "==> Создаём ${ENV_FILE}"
  cat > "${ENV_FILE}" <<EOF
WIFI_INTERFACE=${IFACE}
AP_SSID=SBC-Hotspot
AP_PASSPHRASE=sbc-hotspot
DATA_DIR=/var/lib/sbc-wifi-hotspot
EOF
  echo "    Отредактируйте ${ENV_FILE} под свои нужды"
fi

install -m 0644 deploy/sbc-wifi-hotspot.service "${UNIT}"
systemctl daemon-reload
systemctl enable --now sbc-wifi-hotspot.service

echo "Готово. Логи: journalctl -u sbc-wifi-hotspot -f"

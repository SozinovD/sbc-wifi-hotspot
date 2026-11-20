# sbc-wifi-hotspot

Wi-Fi менеджер для одноплатников (разрабатывался под Radxa Zero 3W): подключается к известным сетям, а если таких нет (или в них нет интернета) — поднимает точку доступа с captive-порталом, через который можно выбрать сеть, ввести пароль и проверить наличие интернета.

## Возможности

- Автоподключение к известным сетям (`wpa_supplicant`, конфиг сохраняется в volume)
- Точка доступа (WPA2, `hostapd` + `dnsmasq`) с DHCP и DNS-перенаправлением
- Captive-портал: при подключении к точке доступа страница со списком сетей открывается автоматически (iOS/Android/Windows); вручную — `http://192.168.4.1`
- Ввод пароля через веб-страницу (в т.ч. скрытые сети), проверка подключения и **наличия интернета**
- Нет интернета → сеть забывается, точка доступа поднимается снова, на портале видна причина
- Сеть сохраняется в известные только после успешной проверки интернета
- Мониторинг: при потере интернета/связи — возврат к циклу подключения и, при необходимости, к точке доступа
- Опциональный периодический повтор попытки известных сетей из режима AP (`AP_CLIENT_RETRY_INTERVAL`)

## Как работает

```
            ┌────────────────────────────────────────────────┐
            │                                                │
            ▼                                                │
known networks ──► connect ──► интернет? ──да──► client mode │
    │нет                │нет         (мониторинг)            │
    ▼                   ▼                                     │
  AP + портал ◄──── отключиться, забыть сеть                 │
    │                                                        │
    └─ пользователь вводит пароль ──► connect + dhcp + check ┘
```

## Запуск: Docker или напрямую?

Сервис управляет хостовым Wi-Fi: поднимает/останавливает `wpa_supplicant`, `hostapd`, `dnsmasq` и `dhclient` на конкретном беспроводном интерфейсе. Поэтому **любой** вариант запуска требует:

- `network_mode: host` (контейнер обязан работать в сетевом namespace хоста);
- capabilities `NET_ADMIN` + `NET_RAW` и root внутри контейнера;
- интерфейс не должен управляться NetworkManager (иначе два менеджера будут конфликтовать).

В Docker это всё достижимо (см. `docker-compose.yml`) — контейнер даёт версионирование через GHCR, воспроизводимое окружение и простое обновление на SBC, поэтому **рекомендуемый способ — Docker**. Если Docker на плате не нужен — тот же код запускается напрямую как systemd-сервис через `scripts/install.sh`. «Классическая» изоляция контейнера здесь всё равно условная: сетевой стек используется хостовый.

## Быстрый старт (Docker)

```bash
cp .env.example .env    # укажите WIFI_INTERFACE, AP_SSID, AP_PASSPHRASE
docker compose up -d
```

Или стек в Portainer (образ публикуется в GHCR из `main`):

```yaml
services:
  sbc-wifi-hotspot:
    image: ghcr.io/sozinovd/sbc-wifi-hotspot:latest
    restart: unless-stopped
    network_mode: host
    cap_add: [NET_ADMIN, NET_RAW]
    environment:
      WIFI_INTERFACE: mlan0
      AP_SSID: SBC-Hotspot
      AP_PASSPHRASE: your-password
    volumes:
      - hotspot-data:/data

volumes:
  hotspot-data:
```

## Radxa Zero 3W

- Wi-Fi интерфейс в Radxa OS обычно называется `mlan0` — укажите `WIFI_INTERFACE=mlan0`
- NetworkManager по умолчанию управляет Wi-Fi. Исключите интерфейс:

```
sudo tee /etc/NetworkManager/conf.d/10-sbc-wifi-hotspot.conf <<'EOF'
[keyfile]
unmanaged-devices=interface-name:mlan0
EOF
sudo systemctl restart NetworkManager
```

- Сохранённые сети: volume `hotspot-data` → `/data/wpa_supplicant.conf`

## Запуск напрямую (systemd)

```bash
sudo WIFI_INTERFACE=mlan0 bash scripts/install.sh
```

Скрипт: ставит пакеты (`hostapd dnsmasq wpasupplicant iw iproute2 isc-dhcp-client`), отключает системные `wpa_supplicant`/`hostapd`/`dnsmasq`, исключает интерфейс из NetworkManager, копирует код в `/opt/sbc-wifi-hotspot`, создаёт venv и включает `sbc-wifi-hotspot.service`. Настройки — `/etc/sbc-wifi-hotspot.env`.

Логи: `journalctl -u sbc-wifi-hotspot -f`.

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `WIFI_INTERFACE` | `wlan0` | Wi-Fi интерфейс (`mlan0` на Radxa Zero 3W) |
| `AP_SSID` | `SBC-Hotspot` | Имя точки доступа |
| `AP_PASSPHRASE` | `sbc-hotspot` | Пароль точки (8–63 символа, смените!) |
| `AP_IP` | `192.168.4.1` | IP точки доступа и портала |
| `AP_CHANNEL` / `AP_HW_MODE` | `6` / `g` | Канал и диапазон (`g`/`a`) |
| `PORTAL_PORT` | `80` | Порт портала (80 нужен для captive-редиректа) |
| `CLIENT_WAIT_TIMEOUT` | `45` | Ожидание известной сети при старте, с |
| `CONNECT_TIMEOUT` | `25` | Ожидание подключения после ввода пароля, с |
| `INTERNET_CHECK_URLS` | встроенный список | URL для проверки интернета (через запятую) |
| `INTERNET_LOSS_RETRIES` | `5` | Подряд неудачных проверок до падения в AP |
| `MONITOR_INTERVAL` | `30` | Интервал мониторинга в client mode, с |
| `AP_CLIENT_RETRY_INTERVAL` | `0` (выкл) | Повтор известных сетей из режима AP, с |
| `WIFI_COUNTRY` | `00` | Country code (`ctrl_interface`/regdomain) |
| `DATA_DIR` | `/data` | Хранилище `wpa_supplicant.conf` |
| `LOG_LEVEL` | `INFO` | Уровень логирования |

## Как устроено

```
supervisor ─┬─ wpa_supplicant ── managed mode (известные сети, DHCP, интернет)
            ├─ hostapd + dnsmasq ── AP mode (DHCP + DNS «все имена → 192.168.4.1»)
            ├─ waitress/flask ── портал: список сетей (iw scan), ввод пароля
            └─ проверка интернета (параллельные HTTP-пробы)
```

Captive-редирект: DNS отдаёт IP точки для любого домена, а веб-сервер на любой неизвестный путь отвечает `302` на `http://192.168.4.1/` — ОС устройства считает, что требуется авторизация, и открывает портал.

## CI

GitHub Actions (`.github/workflows/docker.yml`):

- На каждый push в `main` создаётся git-тег со следующей patch-версией (`v0.1.0`, `v0.1.1`, …), а multi-arch образ (`linux/amd64`, `linux/arm64`) публикуется в `ghcr.io/sozinovd/sbc-wifi-hotspot` с этим же тегом (+ `latest` и `sha-<commit>`).
- Ручной push тега `v*` тоже собирает образ с этим тегом.
- PR в `main` — только сборка, без публикации.

## License

MIT
